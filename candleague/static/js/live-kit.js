// The small kit of the 여러 차트 screen (copied from the demo lab's live-kit.js and cut to what the grid needs): the
// timeframes, price words, one entry per open position of /api/positions (the candidate league has one position per
// account, so a group is a single account's entry) and the candle chart that lays those entries over the candles as
// price lines (the vendored lightweight-charts through chart.js). Text is always text (dom.js h()).
import * as fmt from "./fmt.js";
import {loadLwc, tok, color} from "./chart.js";

export const TFS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];
export const TF_SHORT = {"1m": "1분", "5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일"};
export const TF_MS = {"1m": 60000, "5m": 300000, "15m": 900000, "30m": 1800000, "1h": 3600000, "4h": 14400000, "1d": 86400000};
export const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };
export const px = (p) => (fmt.bad(p) ? "—" : fmt.num(p, priceDec(p)));

/** /api/positions rows -> one entry each, newest first: {id, name, side, coin, lev, entry, stop, target, lock, entry_ms}.
 *  A row without a price (a hidden DeepSeek account has none, D11) or a side is left out. */
export function groupEntries(rows) {
  const out = [];
  for (const p of Array.isArray(rows) ? rows : []) {
    if (!p || typeof p !== "object" || p.hidden || fmt.bad(p.entry) || !Number(p.entry) || !Number(p.side)) continue;
    out.push({id: String(p.id ?? ""), name: p.name ? String(p.name) : "", coin: p.coin, side: Number(p.side) > 0 ? 1 : -1,
      lev: fmt.bad(p.lev) ? null : Number(p.lev), entry: Number(p.entry), stop: fmt.bad(p.stop) ? null : Number(p.stop),
      target: fmt.bad(p.tp) ? null : Number(p.tp), lock: p.stop_is_lock === true, entry_ms: Number(p.since) || 0});
  }
  return out.sort((a, b) => b.entry_ms - a.entry_ms || (a.id < b.id ? -1 : 1));
}
export const levText = (g) => (g.lev ? `${fmt.int(g.lev)}배` : "");
/** The distance from the price to the stop, as the adverse move ("−1.2%"). */
export function stopText(g, price) {
  const p = Number(price);
  if (fmt.bad(g.stop) || !(p > 0)) return "—";
  const d = Math.abs(p - g.stop) / p * 100;
  return `−${fmt.num(d, d < 1 ? 2 : 1)}%`;
}
/** The words under the price dot: where the prices come from (the answer of /api/live). */
export function liveNote(d) {
  if (!d) return "시세 불러오는 중";
  if (d.off) return "실시간 시세 꺼짐";
  if (d.unavailable) return "바이낸스 시세를 받지 못함 · 잠시 뒤 다시 시도";
  return d.stale ? "바이낸스 공개 시세 · 새로 받지 못해 지난 값" : "바이낸스 공개 시세";
}

function kstTick(t, type) {
  const d = new Date(t * 1000 + 9 * 3.6e6), two = (x) => String(x).padStart(2, "0");
  if (type === 0) return String(d.getUTCFullYear());
  if (type === 1) return `${d.getUTCMonth() + 1}월`;
  if (type === 2) return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
  return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
}
const kstTime = (t) => {
  const d = new Date(t * 1000 + 9 * 3.6e6), two = (x) => String(x).padStart(2, "0");
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
};

/** liveChart(box, {volume, compact}) -> {set(bars, tf, keep), merge(bars), tick(price), volume(on), lines(groups, opts), dispose()}
 *  bars: /api/klines "bars" ({t, o, h, l, c, v}); groups: groupEntries() rows of this coin. */
export async function liveChart(box, o = {}) {
  const LW = await loadLwc();
  let dec = 2, tf = "15m";
  const chart = LW.createChart(box, {
    width: box.clientWidth, height: box.clientHeight,
    layout: {background: {color: tok("--surface")}, textColor: tok("--ink-2"), fontSize: o.compact ? 11 : 12, fontFamily: tok("--f-body")},
    grid: {vertLines: {color: tok("--line")}, horzLines: {color: tok("--line")}},
    rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.08, bottom: o.volume ? 0.2 : 0.08}},
    timeScale: {borderColor: tok("--line-2"), timeVisible: true, secondsVisible: false, tickMarkFormatter: kstTick, rightOffset: 4},
    crosshair: {mode: 0},
    localization: {locale: "ko-KR", priceFormatter: (p) => fmt.num(p, dec), timeFormatter: kstTime},
    handleScroll: {vertTouchDrag: false}, handleScale: {axisPressedMouseMove: false},
  });
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => chart.resize(box.clientWidth, box.clientHeight)) : null;
  if (ro) ro.observe(box);
  const up = color("--up"), down = color("--down");
  const candles = chart.addCandlestickSeries({upColor: up, downColor: down, borderUpColor: up, borderDownColor: down,
    wickUpColor: up, wickDownColor: down, priceLineVisible: true, priceLineColor: color("--accent"), priceLineStyle: 2, lastValueVisible: true});
  let vol = null;
  if (o.volume) {
    vol = chart.addHistogramSeries({priceScaleId: "vol", priceFormat: {type: "volume"}, lastValueVisible: false, priceLineVisible: false});
    chart.priceScale("vol").applyOptions({scaleMargins: {top: 0.84, bottom: 0}});
  }
  const volUp = color("--vol-up", "--up"), volDn = color("--vol-down", "--down");
  let data = [], plines = [], lastKey = "";
  const rowOf = (b, i) => [b.t[i], b.o[i], b.h[i], b.l[i], b.c[i]].map(Number);
  return {
    chart,
    /** bars of one timeframe; keep: keep the viewer's scroll position (a refresh of the same coin and timeframe) */
    set(bars, newTf, keep) {
      tf = newTf || tf;
      const b = bars || {}, t = b.t || [];
      const out = [], vs = [];
      for (let i = 0; i < t.length; i++) {
        const row = rowOf(b, i);
        if (row.some((x) => !Number.isFinite(x))) continue;
        const time = Math.floor(row[0] / 1000);
        if (out.length && time <= out[out.length - 1].time) continue;
        out.push({time, open: row[1], high: row[2], low: row[3], close: row[4]});
        if (vol) vs.push({time, value: Number(b.v && b.v[i]) || 0, color: row[4] >= row[1] ? volUp : volDn});
      }
      data = out;
      dec = priceDec(out.length ? out[out.length - 1].close : 1);
      candles.applyOptions({priceFormat: {type: "price", precision: dec, minMove: Math.pow(10, -dec)}});
      const range = keep ? chart.timeScale().getVisibleLogicalRange() : null;
      candles.setData(out);
      if (vol) vol.setData(vs);
      if (range) chart.timeScale().setVisibleLogicalRange(range);
      else if (out.length) {
        const n = o.compact ? 90 : Math.max(50, Math.min(200, Math.round(box.clientWidth / 6)));
        chart.timeScale().setVisibleLogicalRange({from: Math.max(0, out.length - n), to: out.length + 3});
      }
    },
    /** the newest bars of a poll (limit=2): the forming bar replaced, a new bar added */
    merge(bars) {
      const b = bars || {}, t = b.t || [];
      for (let i = 0; i < t.length; i++) {
        const row = rowOf(b, i);
        if (row.some((x) => !Number.isFinite(x)) || !data.length) continue;
        const time = Math.floor(row[0] / 1000), last = data[data.length - 1];
        if (time < last.time) continue;
        const bar = {time, open: row[1], high: row[2], low: row[3], close: row[4]};
        if (time === last.time) data[data.length - 1] = bar; else data.push(bar);
        candles.update(bar);
        if (vol) vol.update({time, value: Number(b.v && b.v[i]) || 0, color: bar.close >= bar.open ? volUp : volDn});
      }
    },
    volume(on) {
      if (!vol) return;
      vol.applyOptions({visible: !!on});
      candles.priceScale().applyOptions({scaleMargins: {top: 0.08, bottom: on ? 0.2 : 0.08}});
    },
    /** the forming bar follows the live price (only while it really is the forming bar) */
    tick(price) {
      const p = Number(price);
      if (!data.length || !Number.isFinite(p) || p <= 0) return;
      const b = data[data.length - 1];
      if (Date.now() >= (b.time * 1000) + (TF_MS[tf] || 0)) return;
      const nb = {time: b.time, open: b.open, high: Math.max(b.high, p), low: Math.min(b.low, p), close: p};
      data[data.length - 1] = nb;
      candles.update(nb);
    },
    /** open positions of this coin: one entry line each (green long, red short); the `labels` nearest the price get a
     *  title; stops (dashed) and take-profits (dotted) only when asked */
    lines(groups, opt = {}) {
      const key = JSON.stringify([groups.map((g) => [g.id, g.entry_ms, g.entry, g.stop, g.target]), opt.stops, opt.targets, opt.labels,
        opt.price ? Math.round(Math.log(Number(opt.price)) * 400) : 0]);
      if (key === lastKey) return;
      lastKey = key;
      for (const pl of plines) candles.removePriceLine(pl);
      plines = [];
      const price = Number(opt.price) || (data.length ? data[data.length - 1].close : 0);
      const near = [...groups].sort((a, b) => Math.abs(a.entry - price) - Math.abs(b.entry - price));
      const labelled = new Set(near.slice(0, opt.labels == null ? 5 : opt.labels));
      const onAxis = new Set(near.slice(0, 3));
      for (const g of groups) {
        const lab = labelled.has(g);
        const title = lab ? `${g.side > 0 ? "롱" : "숏"} ${levText(g)} · ${stopText(g, price)} ${g.lock ? "잠금" : "손절"}`.replace("  ", " ") : "";
        plines.push(candles.createPriceLine({price: g.entry, color: color(g.side > 0 ? "--up" : "--down"), lineWidth: 1, lineStyle: 0,
          axisLabelVisible: lab && onAxis.has(g) && !o.compact, title}));
        if (opt.stops && Number.isFinite(g.stop)) {
          plines.push(candles.createPriceLine({price: g.stop, color: color("--warn"), lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: lab ? (g.lock ? "잠금" : "손절") : ""}));
        }
        if (opt.targets && Number.isFinite(g.target)) {
          plines.push(candles.createPriceLine({price: g.target, color: color("--accent"), lineWidth: 1, lineStyle: 1, axisLabelVisible: false, title: lab ? "익절" : ""}));
        }
      }
    },
    dispose() { if (ro) ro.disconnect(); try { chart.remove(); } catch (e) { /* gone */ } },
  };
}

// Charts with the vendored lightweight-charts (same file as the rule bot's, /static/vendor/, no outside host):
// the equity curves of an account's four leverage lines (with the stop-rule twins, CONTRACT 8.2), a plain multi-line
// chart (비교, 실제 비용) and the candle chart of one trade (CONTRACT 8.6). Colours come from the tokens, so both skins
// hold; every line is also named (legend / title), never colour alone.
import {h} from "./dom.js";
import {money, num} from "./fmt.js";

const SRC = "/static/vendor/lightweight-charts.standalone.production.js";
let loading = null;

export function loadLwc() {
  if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
  if (loading) return loading;
  loading = new Promise((ok, bad) => {
    const sc = document.createElement("script");
    sc.src = SRC; sc.async = true;
    sc.onload = () => (window.LightweightCharts ? ok(window.LightweightCharts) : bad(new Error("no chart library")));
    sc.onerror = () => { loading = null; sc.remove(); bad(new Error("chart library failed to load")); };
    document.head.appendChild(sc);
  });
  return loading;
}

export const tok = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const LEV_TOKENS = {20: "--lev-20", 30: "--lev-30", 40: "--lev-40", 50: "--lev-50"};
export const PICK_TOKENS = ["--pick-1", "--pick-2", "--pick-3", "--pick-4"];
export const PICK_DASH = [0, 2, 1, 3];            // solid, dashed, dotted, wide dash: the picks differ without colour too
/** A token's colour as the chart library can take it (it refuses hsl() and var(); a token that points at another
 *  token comes back resolved from getComputedStyle). */
export function color(name, fallback = "--accent") {
  const v = tok(name);
  return v && !/^hsl|var\(/i.test(v) ? v : tok(fallback);
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

/** [[t_ms, v], ...] -> chart points: strictly increasing seconds; at one time the LAST value wins (a ruin restart). */
export function series(points, col = 1) {
  const out = [];
  for (const p of points || []) {
    if (!Array.isArray(p) || p.length <= col || p[col] == null || !Number.isFinite(Number(p[col])) || !Number.isFinite(Number(p[0]))) continue;
    const t = Math.floor(Number(p[0]) / 1000);
    if (out.length && t <= out[out.length - 1].time) {
      if (t === out[out.length - 1].time) out[out.length - 1].value = Number(p[col]);
      continue;
    }
    out.push({time: t, value: Number(p[col])});
  }
  return out;
}

function baseChart(L, box, priceFormatter) {
  return L.createChart(box, {
    width: box.clientWidth, height: box.clientHeight,
    layout: {background: {color: tok("--surface")}, textColor: tok("--ink-2"), fontSize: 12, fontFamily: tok("--f-body")},
    grid: {vertLines: {color: tok("--line")}, horzLines: {color: tok("--line")}},
    rightPriceScale: {borderColor: tok("--line-2")},
    timeScale: {borderColor: tok("--line-2"), timeVisible: true, secondsVisible: false, tickMarkFormatter: kstTick},
    crosshair: {mode: 0},
    localization: {locale: "ko-KR", priceFormatter, timeFormatter: kstTime},
    handleScroll: {vertTouchDrag: false}, handleScale: {axisPressedMouseMove: false},
  });
}
function watchSize(chart, box) {
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => chart.resize(box.clientWidth, box.clientHeight)) : null;
  if (ro) ro.observe(box);
  return ro;
}
const usd = (p) => "$" + num(p, Math.abs(p) >= 100 ? 0 : 2);

/** equityChart(box, seed) -> {update(curves, levs, stopCurves?, mode?), dispose()}; box gets a fixed height from demo.css.
 *  mode: "plain" (the lines as they ran), "stops" (the stop-rule twins only), "both" (twins dashed over the lines). */
export async function equityChart(box, seed = 1000) {
  const L = await loadLwc();
  const chart = baseChart(L, box, usd);
  const lines = {}, twins = {};
  const ro = watchSize(chart, box);
  let baseSet = false;
  return {
    update(curves, levs, stopCurves, mode = "plain") {
      for (const lv of levs) {
        const key = String(lv);
        const c = color(LEV_TOKENS[lv]);
        if (!lines[key]) {
          lines[key] = chart.addLineSeries({color: c, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: `${lv}배`});
          if (!baseSet) {
            lines[key].createPriceLine({price: seed, color: tok("--muted"), lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "시작"});
            baseSet = true;
          }
        }
        lines[key].setData(series(curves && curves[key]));
        if (stopCurves) {
          if (!twins[key]) twins[key] = chart.addLineSeries({color: c, lineWidth: 2, lineStyle: 2, priceLineVisible: false, lastValueVisible: true, title: `${lv}배 정지 규칙`});
          twins[key].setData(series(stopCurves[key]));
        }
      }
      const shown = levs.map(String);
      for (const key of Object.keys(lines)) lines[key].applyOptions({visible: shown.includes(key) && mode !== "stops"});
      for (const key of Object.keys(twins)) twins[key].applyOptions({visible: shown.includes(key) && mode !== "plain"});
      chart.timeScale().fitContent();
    },
    dispose() { if (ro) ro.disconnect(); try { chart.remove(); } catch (e) { /* gone */ } },
  };
}

/** The legend under the chart: each line's colour and its own name (never colour alone). */
export function legend(levs, last) {
  return h("div", {class: "dl-legend"}, levs.map((lv) => h("span", {class: "dl-lg"},
    h("i", {style: {background: `var(${LEV_TOKENS[lv]})`}}), `${lv}배`, last && last[lv] != null ? h("b", null, ` ${money(last[lv])}`) : null)));
}

/** lineChart(box, {format, base, baseTitle}) -> {set([{key, title, token, dash, width, points, col}]), dispose()}:
 *  any number of named lines (비교: the 2-4 picked accounts; 실제 비용: spread and the 10k cost). */
export async function lineChart(box, o = {}) {
  const L = await loadLwc();
  const chart = baseChart(L, box, o.format || ((p) => num(p, 2)));
  const ro = watchSize(chart, box);
  let all = {}, baseLine = null;
  return {
    set(list) {
      const keep = new Set(list.map((x) => x.key));
      for (const [k, sr] of Object.entries(all)) if (!keep.has(k)) { chart.removeSeries(sr); delete all[k]; }
      list.forEach((x, i) => {
        if (!all[x.key]) {
          all[x.key] = chart.addLineSeries({color: color(x.token || PICK_TOKENS[i % 4]), lineWidth: x.width || 2,
            lineStyle: x.dash != null ? x.dash : PICK_DASH[i % 4], priceLineVisible: false, lastValueVisible: true, title: x.title || "",
            // keep the reference line (the start $1,000, the assumed 2 bp) inside the price scale
            autoscaleInfoProvider: o.base == null ? undefined : (orig) => {
              const r = orig();
              if (!r || !r.priceRange) return r;
              return {...r, priceRange: {minValue: Math.min(r.priceRange.minValue, o.base), maxValue: Math.max(r.priceRange.maxValue, o.base)}};
            }});
          if (o.base != null && !baseLine) {
            baseLine = all[x.key].createPriceLine({price: o.base, color: tok("--muted"), lineWidth: 1, lineStyle: 2,
              axisLabelVisible: true, title: o.baseTitle || ""});
          }
        } else {
          all[x.key].applyOptions({title: x.title || ""});
        }
        all[x.key].setData(series(x.points, x.col || 1));
      });
      chart.timeScale().fitContent();
    },
    dispose() { if (ro) ro.disconnect(); try { chart.remove(); } catch (e) { /* gone */ } all = {}; },
  };
}

const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };

/** candleChart(box) -> {set(bars, trade), dispose()}: the candles of one coin and the trade on them (CONTRACT 8.6):
 *  price lines for the entry, the stop and (fixed pairs only) the target; markers at the entry and the exit.
 *  bars: [[t_ms, o, h, l, c], ...]; trade: {side, entry, stop, target, exit, entry_ms, exit_ms, tf_ms, exit_label}. */
export async function candleChart(box) {
  const L = await loadLwc();
  let dec = 2;
  const chart = baseChart(L, box, (p) => num(p, dec));
  const ro = watchSize(chart, box);
  const up = color("--up"), down = color("--down");
  const candles = chart.addCandlestickSeries({upColor: up, downColor: down, borderUpColor: up, borderDownColor: down,
    wickUpColor: up, wickDownColor: down, priceLineVisible: false, lastValueVisible: true});
  let plines = [];
  return {
    set(bars, t) {
      const data = [];
      for (const b of bars || []) {
        if (!Array.isArray(b) || b.length < 5 || b.slice(0, 5).some((x) => !Number.isFinite(Number(x)))) continue;
        const time = Math.floor(Number(b[0]) / 1000);
        if (data.length && time <= data[data.length - 1].time) continue;
        data.push({time, open: Number(b[1]), high: Number(b[2]), low: Number(b[3]), close: Number(b[4])});
      }
      dec = priceDec(t && t.entry != null ? t.entry : data.length ? data[data.length - 1].close : 1);
      candles.applyOptions({priceFormat: {type: "price", precision: dec, minMove: Math.pow(10, -dec)}});
      candles.setData(data);
      for (const pl of plines) candles.removePriceLine(pl);
      plines = [];
      if (!t) { chart.timeScale().fitContent(); return; }
      const line = (price, token, style, title) => {
        if (price == null || !Number.isFinite(Number(price))) return;
        plines.push(candles.createPriceLine({price: Number(price), color: color(token), lineWidth: 2, lineStyle: style,
          axisLabelVisible: true, title}));
      };
      line(t.entry, "--accent", 0, "진입");
      line(t.stop, "--down", 2, "손절");
      line(t.target, "--up", 2, "목표");
      if (t.exit != null) line(t.exit, "--ink-2", 1, "청산");
      // markers sit on the bar that holds the moment (an exit time is the end of its bar: look 1 ms earlier)
      const barOf = (ms) => {
        if (ms == null || !data.length) return null;
        const s = Math.floor((Number(ms)) / 1000);
        let pick = null;
        for (const d of data) { if (d.time <= s) pick = d.time; else break; }
        return pick;
      };
      const marks = [];
      const long = Number(t.side) > 0;
      const eT = barOf(t.entry_ms);
      if (eT != null) marks.push({time: eT, position: long ? "belowBar" : "aboveBar", color: color("--accent"),
        shape: long ? "arrowUp" : "arrowDown", text: long ? "롱 진입" : "숏 진입"});
      const xT = t.exit_ms != null ? barOf(Number(t.exit_ms) - 1) : null;
      if (xT != null) marks.push({time: xT, position: long ? "aboveBar" : "belowBar", color: color(t.win ? "--up" : "--down"),
        shape: "circle", text: t.exit_label || "청산"});
      marks.sort((a, b) => a.time - b.time);
      candles.setMarkers(marks);
      // show the trade with some room around it (the rest of the window stays one drag away)
      if (eT != null && data.length) {
        const span = Math.max(((xT != null ? xT : data[data.length - 1].time) - eT), 3600);
        const from = Math.max(data[0].time, eT - Math.max(span * 1.2, 12 * 3600));
        const to = Math.min(data[data.length - 1].time, (xT != null ? xT : eT) + Math.max(span * 0.6, 6 * 3600));
        try { chart.timeScale().setVisibleRange({from, to}); } catch (e) { chart.timeScale().fitContent(); }
      } else {
        chart.timeScale().fitContent();
      }
    },
    dispose() { if (ro) ro.disconnect(); try { chart.remove(); } catch (e) { /* gone */ } },
  };
}

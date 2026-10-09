// The equity curves of an account's four leverage lines, drawn with the vendored lightweight-charts (same file as the
// rule bot's, /static/vendor/, no outside host). Colours come from the tokens, so both skins hold.
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

function kstTick(t, type) {
  const d = new Date(t * 1000 + 9 * 3.6e6), two = (x) => String(x).padStart(2, "0");
  if (type === 0) return String(d.getUTCFullYear());
  if (type === 1) return `${d.getUTCMonth() + 1}월`;
  if (type === 2) return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
  return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
}

function series(points) {
  const out = [];
  let last = -1;
  for (const p of points || []) {
    if (!Array.isArray(p) || p.length < 2 || p[1] == null || !Number.isFinite(Number(p[1]))) continue;
    const t = Math.floor(Number(p[0]) / 1000);
    if (!(t > last)) continue;                       // strictly increasing times only
    out.push({time: t, value: Number(p[1])});
    last = t;
  }
  return out;
}

/** equityChart(box, seed) -> {update(curves, levs), dispose()} ; box gets a fixed height from demo.css. */
export async function equityChart(box, seed = 1000) {
  const L = await loadLwc();
  const chart = L.createChart(box, {
    width: box.clientWidth, height: box.clientHeight,
    layout: {background: {color: tok("--surface")}, textColor: tok("--ink-2"), fontSize: 12, fontFamily: tok("--f-body")},
    grid: {vertLines: {color: tok("--line")}, horzLines: {color: tok("--line")}},
    rightPriceScale: {borderColor: tok("--line-2")},
    timeScale: {borderColor: tok("--line-2"), timeVisible: true, secondsVisible: false, tickMarkFormatter: kstTick},
    crosshair: {mode: 0},
    localization: {locale: "ko-KR", priceFormatter: (p) => "$" + num(p, Math.abs(p) >= 100 ? 0 : 2), timeFormatter: (t) => {
      const d = new Date(t * 1000 + 9 * 3.6e6), two = (x) => String(x).padStart(2, "0");
      return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
    }},
    handleScroll: {vertTouchDrag: false}, handleScale: {axisPressedMouseMove: false},
  });
  const lines = {};
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => chart.resize(box.clientWidth, box.clientHeight)) : null;
  if (ro) ro.observe(box);
  let baseSet = false;
  return {
    update(curves, levs) {
      for (const lv of levs) {
        const key = String(lv);
        if (!lines[key]) {
          lines[key] = chart.addLineSeries({color: tok(LEV_TOKENS[lv]) || tok("--accent"), lineWidth: 2, priceLineVisible: false,
            lastValueVisible: true, title: `${lv}배`});
          if (!baseSet) {
            lines[key].createPriceLine({price: seed, color: tok("--muted"), lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "시작"});
            baseSet = true;
          }
        }
        lines[key].setData(series(curves && curves[key]));
      }
      for (const key of Object.keys(lines)) lines[key].applyOptions({visible: levs.map(String).includes(key)});
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

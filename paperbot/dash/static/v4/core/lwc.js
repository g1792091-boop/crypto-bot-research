// The candle chart library the old UI already ships (same origin: /static/vendor/lightweight-charts...js, v4 API,
// window.LightweightCharts). Loaded once, only by the screens that draw candles. Colours come from the tokens.
const SRC = "/static/vendor/lightweight-charts.standalone.production.js";
let loading = null;

/** Promise of window.LightweightCharts (rejects when the file cannot load; show ui.errorBox then). */
export function loadLwc() {
  if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
  if (loading) return loading;
  loading = new Promise((ok, bad) => {
    const sc = document.createElement("script");
    sc.src = SRC; sc.async = true;
    sc.onload = () => (window.LightweightCharts ? ok(window.LightweightCharts) : bad(new Error("no LightweightCharts")));
    sc.onerror = () => { loading = null; sc.remove(); bad(new Error("chart library failed to load")); };
    document.head.appendChild(sc);
  });
  return loading;
}

/** Korea-time axis labels: year, "10월", "10/5", "14:05" (lightweight-charts tick types 0-4). */
export function kstTick(t, type) {
  const d = new Date(t * 1000 + 9 * 3.6e6), two = (x) => String(x).padStart(2, "0");
  if (type === 0) return String(d.getUTCFullYear());
  if (type === 1) return `${d.getUTCMonth() + 1}월`;
  if (type === 2) return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
  return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
}
/** Price decimals by size, the same steps as fmt.price (for a series' priceFormat precision). */
export const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };

export const tok = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** Chart options in the dashboard's colours (Korea time on the time axis and the crosshair). */
export function chartOptions(el) {
  return {
    width: el.clientWidth, height: el.clientHeight,
    layout: {background: {color: tok("--surface")}, textColor: tok("--ink-2"), fontSize: 11, fontFamily: tok("--f-body")},
    grid: {vertLines: {color: tok("--line")}, horzLines: {color: tok("--line")}},
    rightPriceScale: {borderColor: tok("--line-2")},
    timeScale: {borderColor: tok("--line-2"), timeVisible: true, secondsVisible: false, tickMarkFormatter: kstTick},
    crosshair: {mode: 0},
    localization: {locale: "ko-KR", timeFormatter: (t) => {
      const d = new Date(t * 1000 + 9 * 3.6e6);
      return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
    }},
  };
}
export const candleOptions = () => ({upColor: tok("--up"), downColor: tok("--down"), borderVisible: false,
  wickUpColor: tok("--up"), wickDownColor: tok("--down")});

/** Create a chart that follows its box's size; returns {chart, dispose}. Pass dispose to ctx.track(). */
export async function makeChart(el, extra = {}) {
  const L = await loadLwc();
  const chart = L.createChart(el, {...chartOptions(el), ...extra});
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => chart.resize(el.clientWidth, el.clientHeight)) : null;
  if (ro) ro.observe(el);
  return {chart, L, dispose: () => { if (ro) ro.disconnect(); try { chart.remove(); } catch (e) { /* gone */ } }};
}

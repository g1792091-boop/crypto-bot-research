// 매매법 차트 (builder C): one strategy on one coin and timeframe, with the vendored lightweight-charts (same origin).
// Candles from /api/candles; the indicator lines and lower panes exactly as the strategy's locked code uses them, from
// /api/strategy/<name> (the old strat.js view). A strategy without a chart view (DeepSeek and the reel today: 404 / 400)
// still shows its candles and its account's entries and exits, and says the lines are '준비 전'. Colours: tokens only.
import {h, put, ui, fmt, makeChart, candleOptions, tok} from "../core/pb.js";

const PALETTE = ["--term-cyan", "--accent", "--ink-2", "--warn", "--amber-ink"];
const TF_S = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400};

/** /api/strategy/<id>: the 36 (listed by /api/strategies) and the 44 DeepSeek definitions and the reel by their own id
 *  (kind ds200 / reel; paperbot/strategy_views.py has_view). 5m only for the reel; DeepSeek and the reel never trade
 *  XRP. A 404 / 400 / 503 (no view yet, refused, no prices) gives null = '준비 전', never a made-up line. */
export async function loadView(ctx, name, tf, sym, list, kind) {
  const e = (list || []).find((s) => s.strategy === name);
  const v4 = kind === "ds200" || kind === "reel";
  if ((!e && !v4) || (e && e.view === false) || (tf === "5m" && kind !== "reel")) return null;
  if (v4 && sym === "XRPUSDT") return null;
  const q = `?tf=${encodeURIComponent(tf)}&symbol=${encodeURIComponent(sym)}`;
  try { return await ctx.api(`/api/strategy/${encodeURIComponent((e && e.view_id) || name)}${q}`); } catch (err) {
    if (err && (err.status === 404 || err.status === 400 || err.status === 503)) return null;
    throw err;
  }
}

/**
 * stratChart(ctx) -> {el, legend, draw(o), dispose}
 * o = {name, ko, tf, sym, bars, view, trades (this account's, closed), position (board), markers (bool)}
 */
export function stratChart(ctx) {
  const box = h("div", {class: "strat-chartbox", role: "img", "aria-label": "매매법 차트"});
  const legend = h("p", {class: "strat-legend"});
  const note = h("p", {class: "strat-chartnote muted", hidden: true});
  const el = h("div", {class: "stack tight"}, box, legend, note);
  let C = null, series = null, extra = [], lines = [], failed = false, dead = false;
  let drawing = Promise.resolve();

  let making = null;
  function ensure() {                         // one chart per box, however many draws arrive at once
    if (!making) making = (async () => {
      try {
        C = await makeChart(box, {rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.05, bottom: 0.05}}});
      } catch {
        failed = true;
        put(box, ui.errorBox(null));
        return false;
      }
      if (dead) { C.dispose(); C = null; return false; }
      series = C.chart.addCandlestickSeries(candleOptions());
      return true;
    })();
    return making.then((ok) => ok && !!C && !failed);
  }

  function draw(o) { drawing = drawing.then(() => drawNow(o)).catch((e) => console.error(e)); return drawing; }
  async function drawNow(o) {
    if (!(await ensure()) || dead) return;
    const {chart} = C;
    const lastPx = (o.bars || []).length ? Math.abs(o.bars[o.bars.length - 1].close) : 0;
    const prec = lastPx < 1 ? 5 : lastPx < 10 ? 4 : lastPx < 1000 ? 2 : 1;      // the same decimals as fmt.price
    series.applyOptions({priceFormat: {type: "price", precision: prec, minMove: 1 / 10 ** prec}});
    series.setData(o.bars || []);
    for (const x of extra) { try { chart.removeSeries(x); } catch { /* gone */ } }
    extra = [];
    const v = o.view;
    const col = (i) => tok(PALETTE[i % PALETTE.length]);
    // a v4 level / zone line comes with "step" (drawn with steps: a new level starts with a vertical jump) and with
    // time-only points where it is not live (the server's whitespace points end it there, so each zone is its own box)
    if (v && v.overlays) v.overlays.forEach((ov, i) => {
      const sr = chart.addLineSeries({color: col(i), lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, title: ov.name, lineType: ov.step ? 1 : 0});
      sr.setData(ov.data || []); extra.push(sr);
    });
    const panes = (v && v.panes) || [];
    panes.forEach((p, k) => {
      const scale = `pane${k}`;
      (p.series || []).forEach((ln, i) => {
        const hist = /히스토그램/.test(ln.name || "");
        const sr = hist
          ? chart.addHistogramSeries({priceScaleId: scale, priceLineVisible: false, lastValueVisible: false})
          : chart.addLineSeries({color: col(i + 1), lineWidth: 1.5, priceScaleId: scale, priceLineVisible: false,
            lastValueVisible: i === 0, crosshairMarkerVisible: false, title: i === 0 ? p.name : "", lineType: ln.step ? 1 : 0});
        sr.setData(hist ? (ln.data || []).filter((d) => d.value != null).map((d) => ({...d, color: d.value >= 0 ? tok("--up-line") : tok("--down-line")})) : (ln.data || []));
        if (i === 0) (p.levels || []).forEach((lv) => sr.createPriceLine({price: lv, color: tok("--line-2"), lineWidth: 1, lineStyle: 2, axisLabelVisible: false}));
        extra.push(sr);
      });
      chart.priceScale(scale).applyOptions({scaleMargins: {top: 0.78 - 0.2 * k, bottom: 0.02 + 0.2 * k}});
    });
    chart.priceScale("right").applyOptions({scaleMargins: {top: 0.05, bottom: panes.length ? 0.06 + 0.22 * panes.length : 0.05}});
    // this account's entries (arrows) and exits (dots with the ROE): the details are in the lists below
    const step = TF_S[o.tf] || 900, bs = o.bars || [], t0 = bs.length ? bs[0].time : 0, marks = [];
    if (o.markers) for (const t of o.trades || []) {
      if (t.symbol !== o.sym) continue;
      const e = Math.floor(t.entry_time / 1000), x = Math.floor(t.exit_time / 1000);
      if (e >= t0) marks.push({time: e - (e % step), position: t.side > 0 ? "belowBar" : "aboveBar", color: tok("--accent"),
        shape: t.side > 0 ? "arrowUp" : "arrowDown", text: ""});
      if (x >= t0) marks.push({time: x - (x % step), position: t.side > 0 ? "aboveBar" : "belowBar",
        color: t.pnl > 0 ? tok("--up") : tok("--down"), shape: "circle", text: fmt.pct(t.roe, 0)});
    }
    marks.sort((a, b) => a.time - b.time);
    series.setMarkers(marks);
    for (const l of lines) { try { series.removePriceLine(l); } catch { /* gone */ } }
    lines = [];
    const p = o.position;
    if (p && p.symbol === o.sym) {
      const add = (price, color, style, title) => { if (price) lines.push(series.createPriceLine({price, color, lineWidth: 1, lineStyle: style, title})); };
      add(p.entry, tok("--accent"), 0, `진입 ${fmt.sideKo(p.side)} ${fmt.lev(p.leverage)}`);
      add(p.stop, p.lock_roe != null ? tok("--up") : tok("--down"), 2, p.lock_roe != null ? `잠금 ${fmt.pct(p.lock_roe, 0)}` : "손절");
      add(p.liq, tok("--warn"), 3, "청산가");
      if (p.target) add(p.target, tok("--up"), 2, "목표 (윗밴드)");
    }
    chart.timeScale().fitContent();
    const last = bs[bs.length - 1];
    put(legend, h("b", null, o.ko), ` · ${fmt.coin(o.sym)} ${fmt.tfKo(o.tf)}`,
      last ? [" · 종가 ", h("b", {class: "num"}, fmt.price(last.close))] : null,
      v ? h("span", {class: "muted"}, ` · 지표 ${(v.overlays || []).length + panes.length}개`) : null);
    note.hidden = !!v;
    note.textContent = v ? "" : "이 매매법의 지표 선과 조건표는 서버에 아직 없습니다 (차트 보기 준비 전). 가격과 이 계좌의 진입·청산만 보입니다.";
  }

  return {el, draw, dispose: () => { dead = true; if (C) C.dispose(); C = null; }};
}

// 자체 차트 엔진 (lightweight-charts v5 + 자체 보조지표 + 오버레이)
import { INDICATORS, volumeProfile } from "./ind.js";
import { IV_LABEL, api, big, css, esc, fmt, px } from "./core.js";

const LC = LightweightCharts;

// 캔버스에 직접 그리는 레이어 (청산맵 · 고래 · 호가벽 · 추세선). 차트와 함께 확대/이동된다.
class Layer {
  constructor(draw, z = "bottom") {
    this.draw = draw;
    this._z = z;
    this._view = { zOrder: () => this._z, renderer: () => ({ draw: (t) => t.useMediaCoordinateSpace(({ context, mediaSize }) => this.p && this.draw(context, mediaSize, this.p)) }) };
  }
  attached(p) { this.p = p; }
  detached() { this.p = null; }
  paneViews() { return [this._view]; }
  update() { this.p?.requestUpdate(); }
}

// 봉 마감까지 남은 시간
const IV_SEC = { "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
  "8h": 28800, "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800 };
export function barEnd(openTime, iv) {
  if (iv === "1M" || iv === "1y") {
    const d = new Date(openTime * 1000);
    return Date.UTC(d.getUTCFullYear() + (iv === "1y" ? 1 : 0), iv === "1M" ? d.getUTCMonth() + 1 : 0, 1) / 1000;
  }
  return openTime + (IV_SEC[iv] || 3600);
}
export function fmtLeft(sec) {
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60), x = sec % 60, z = (n) => String(n).padStart(2, "0");
  return d ? `${d}일 ${z(h)}:${z(m)}:${z(x)}` : h ? `${z(h)}:${z(m)}:${z(x)}` : `${z(m)}:${z(x)}`;
}

// 가격축의 현재가 라벨 바로 아래에 남은 시간을 표시 (트레이딩뷰 방식)
class Countdown {
  constructor(tc) {
    this.tc = tc; this.y = null; this.text = ""; this.bg = "#444";
    this._view = { coordinate: () => this.y ?? -100, text: () => this.text, textColor: () => "#fff", backColor: () => this.bg, visible: () => !!this.text, tickVisible: () => false };
  }
  attached(p) { this.p = p; }
  detached() { this.p = null; }
  updateAllViews() {
    const tc = this.tc, b = tc.candles.at(-1);
    if (!b || tc.opts.overlays.countdown === false) { this.text = ""; return; }
    const y = tc.candle.priceToCoordinate(b.close);
    if (y == null) { this.text = ""; return; }
    this.y = y + (tc.chart.options().layout.fontSize || 11) + 7;
    this.text = fmtLeft(barEnd(b.time, tc.interval) - Date.now() / 1000);
    this.bg = b.close >= b.open ? css("--up") : css("--down");
  }
  priceAxisViews() { return [this._view]; }
  update() { this.p?.requestUpdate(); }
}

export class TermChart {
  constructor(el, opts = {}) {
    this.el = el;
    this.opts = { overlays: { heat: false, whales: false, bots: true, scenario: true }, ...opts };
    this.symbol = opts.symbol; this.interval = opts.interval;
    this.indicators = opts.indicators || [];
    this.candles = [];
    this.ind = [];            // {spec, series:[], pane}
    this.ext = {};            // 서버 파생 데이터
    this.heat = null; this.whales = null; this.markers = null; this.scenario = null;
    this.priceLines = []; this.userLines = []; this.trends = [];
    this.drawMode = null; this.pending = null;

    el.innerHTML = `<div class="tc-chart"></div><div class="tc-legend"></div>`;
    this.legendEl = el.querySelector(".tc-legend");
    this.chart = LC.createChart(el.querySelector(".tc-chart"), {
      autoSize: true,
      layout: { background: { type: "solid", color: css("--panel") }, textColor: css("--text-2"), fontSize: 11,
        fontFamily: getComputedStyle(document.body).fontFamily, panes: { separatorColor: css("--line"), separatorHoverColor: "rgba(245,165,36,.25)" } },
      grid: { vertLines: { color: "rgba(255,255,255,.035)" }, horzLines: { color: "rgba(255,255,255,.035)" } },
      rightPriceScale: { borderColor: css("--line") },
      timeScale: { borderColor: css("--line"), timeVisible: true, secondsVisible: false, rightOffset: 8 },
      crosshair: { mode: LC.CrosshairMode.Normal },
      localization: { locale: "ko-KR", priceFormatter: px },
    });
    this.candle = this.chart.addSeries(LC.CandlestickSeries, { upColor: css("--up"), downColor: css("--down"), borderVisible: false,
      wickUpColor: css("--up"), wickDownColor: css("--down"),
      // 보이는 캔들 + 내 진입·손절·익절만으로 세로 범위를 잡는다 (멀리 있는 강제청산선 때문에 캔들이 눌리지 않게)
      autoscaleInfoProvider: (original) => this._autoscale(original) });
    this.markerApi = LC.createSeriesMarkers(this.candle, []);
    this.heatLayer = new Layer((ctx, size, p) => this._drawHeat(ctx, size, p), "bottom");
    this.whaleLayer = new Layer((ctx, size, p) => this._drawWhales(ctx, size, p), "normal");
    this.drawLayer = new Layer((ctx, size, p) => this._drawTrends(ctx, size, p), "top");
    this.srLayer = new Layer((ctx, size) => this._drawSR(ctx, size), "bottom");
    this.vpLayer = new Layer((ctx, size) => this._drawVP(ctx, size), "bottom");
    this.countdown = new Countdown(this);
    [this.vpLayer, this.srLayer, this.heatLayer, this.whaleLayer, this.drawLayer, this.countdown].forEach((l) => this.candle.attachPrimitive(l));
    this.sigMarkers = [];     // 보조지표 신호 (골든크로스·UT Bot·다이버전스 등) — 가격 창 화살표
    this._cdTimer = setInterval(() => !document.hidden && this.countdown.update(), 1000);
    this.editLines = {};
    this._setupDrag();
    this.chart.subscribeCrosshairMove((p) => this._legend(p));
    this.chart.subscribeClick((p) => this._click(p));
  }

  destroy() { clearInterval(this._timer); clearInterval(this._cdTimer); this.chart.remove(); this.el.innerHTML = ""; }

  // 지금 보고 있는 코인·봉인지 확인 (늦게 도착한 이전 코인의 응답을 버리기 위함)
  _is(sym, iv) { return sym === this.symbol && iv === this.interval; }

  async load(symbol = this.symbol, interval = this.interval) {
    const changed = symbol !== this.symbol || interval !== this.interval || !this.candles.length;
    this.symbol = symbol; this.interval = interval;
    if (changed) {
      // 이전 코인의 포지션선·시나리오·청산맵·고래·지지저항이 새 코인 차트에 남지 않도록 즉시 비운다
      clearInterval(this._timer);
      this.markers = this.heat = this.whales = this.sr = this.scenario = null;
      this.ext = {}; this.sigMarkers = [];
      this._applyMarkers();
      [this.heatLayer, this.whaleLayer, this.srLayer].forEach((l) => l.update());
    }
    let d;
    try { d = await api(`/api/candles?symbol=${symbol}&interval=${interval}&limit=${interval === "1m" ? 1500 : 1000}`); }
    catch (e) {
      // 없는 종목이면 이전 코인 봉을 그대로 두지 말고 비운다 (다른 코인 차트가 새 이름으로 보이는 문제)
      if (this._is(symbol, interval)) {
        this.candles = []; this.candle.setData([]);
        this.ind.forEach((it) => it.series.forEach((s) => s?.setData([])));
        this.sigMarkers = []; this._pushMarkers();
        this._legend();
      }
      throw e;
    }
    if (!this._is(symbol, interval)) return;
    this.source = d.source;
    this.candles = d.candles;
    this.candle.setData(this.candles);
    if (changed) { this.chart.timeScale().fitContent(); this.chart.timeScale().scrollToRealTime(); this._loadDrawings(); }
    await this._loadExt();
    if (!this._is(symbol, interval)) return;
    this.renderIndicators();
    this.refreshOverlays();
    this._legend();
    clearInterval(this._timer);
    this._timer = setInterval(() => this._tick(), 3000);
  }

  async _tick() {
    if (document.hidden || !this.candles.length) return;
    const sym = this.symbol, iv = this.interval;
    let d;
    try { d = await api(`/api/candles?symbol=${sym}&interval=${iv}&limit=3`); } catch { return; }
    if (!this._is(sym, iv)) return;   // 그 사이 코인을 바꿨으면 버린다
    let newBar = false;
    for (const b of d.candles) {
      const last = this.candles.at(-1);
      if (b.time === last.time) this.candles[this.candles.length - 1] = b;
      else if (b.time > last.time) { this.candles.push(b); newBar = true; }
      else continue;
      this.candle.update(b);
    }
    this._tickN = (this._tickN || 0) + 1;
    if (newBar || this._tickN % 5 === 0) this.renderIndicators(true);
    if (newBar) this.refreshOverlays();
    this._legend();
    this.editLines.entry?.applyOptions({ title: this._entryTitle() });
    this.opts.onTick?.(this.candles.at(-1));
  }

  // ------------------------------------------------------------ 보조지표
  async _loadExt() {
    const need = new Set(this.indicators.map((i) => INDICATORS[i.key]?.remote).filter(Boolean));
    const sym = this.symbol, iv = this.interval, ext = {};
    const jobs = [];
    if (need.has("derivatives")) jobs.push(api(`/api/derivatives?symbol=${sym}&interval=${iv}&limit=500`).then((d) => Object.assign(ext, d)).catch(() => {}));
    if (need.has("cbp")) jobs.push(api(`/api/coinbase-premium?symbol=${sym}&interval=${iv}`).then((d) => (ext.series = d.series)).catch(() => (ext.series = [])));
    await Promise.all(jobs);
    if (this._is(sym, iv)) this.ext = ext;
  }

  setIndicators(list) { this.indicators = list; this._loadExt().then(() => this.renderIndicators()); }

  renderIndicators(valuesOnly = false) {
    const c = this.candles;
    if (!c.length) return;
    if (valuesOnly && this.ind.length === this.indicators.length) {
      this.ind.forEach((it) => { const r = INDICATORS[it.spec.key].compute(c, it.params, this.ext); r.plots.forEach((pl, k) => it.series[k] && it.series[k].setData(toData(c, pl))); it.last = r; });
      this._applySignals();
      return;
    }
    for (const it of this.ind) { it.markers?.detach(); it.series.forEach((s) => s && this.chart.removeSeries(s)); }
    this.ind = [];
    while (this.chart.panes().length > 1) {
      try { this.chart.removePane(this.chart.panes().length - 1); } catch { break; }
    }
    let paneNo = 0;
    for (const spec of this.indicators) {
      const def = INDICATORS[spec.key];
      if (!def) continue;
      const params = { ...def.params, ...spec.params };
      const r = def.compute(c, params, this.ext);
      const pane = def.pane === "sub" ? ++paneNo : 0;
      const series = r.plots.map((pl) => {
        if (pl.type === "signals") return null;   // 화살표로 표시
        const common = { priceLineVisible: false, lastValueVisible: def.pane === "sub" && pl.legend !== false, title: "" };
        let s;
        if (pl.type === "hist") {
          s = this.chart.addSeries(LC.HistogramSeries, { ...common, ...(def.pane === "volume" ? { priceScaleId: "vol", priceFormat: { type: "volume" } } : {}) }, pane);
        } else {
          s = this.chart.addSeries(LC.LineSeries, { ...common, color: pl.color, lineWidth: pl.lineWidth ?? 2, lineStyle: pl.lineStyle ?? 0,
            crosshairMarkerVisible: false, ...(pl.type === "dots" ? { lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 1.5 } : {}),
            ...(def.pane === "volume" ? { priceScaleId: "vol" } : {}) }, pane);
        }
        s.setData(toData(c, pl));
        return s;
      });
      if (def.pane === "volume") this.chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      const first = series.find(Boolean);
      if (r.levels && first) r.levels.forEach((lv) => first.createPriceLine({ price: lv, color: "rgba(164,172,182,.35)", lineWidth: 1, lineStyle: 2, axisLabelVisible: false }));
      this.ind.push({ spec, params, series, pane, last: r, profile: !!def.profile });
    }
    this._applySignals();
    this.vpLayer.update();
    const panes = this.chart.panes();
    // 가격 창이 항상 절반 이상을 차지하도록
    panes.forEach((p, i) => p.setStretchFactor(i === 0 ? Math.max(2, panes.length - 1) : 1));
    this._legend();
  }

  // 지표 신호 → 마커. 가격 위 지표는 캔들에, 아래 창 지표는 그 지표선에 붙인다
  _applySignals() {
    const c = this.candles, main = [];
    // 오래된 신호는 글자 없이 작은 화살표만 (최근 KEEP 개만 글자 표시 — 차트가 글자로 덮이지 않게)
    const KEEP = 12;
    const toMk = (sg, i, recent, line) => ({ time: c[i].time, shape: sg.shape || (sg.dir > 0 ? "arrowUp" : "arrowDown"),
      color: sg.color || (sg.dir > 0 ? css("--up") : css("--down")), text: recent ? sg.text || "" : "",
      // 아래 창에서는 선 위에 바로 찍는다 (위/아래 여백을 잡아먹어 지표선이 눌리지 않게)
      ...(line ? { position: sg.dir > 0 ? "atPriceBottom" : "atPriceTop", price: line[i] } : { position: sg.dir > 0 ? "belowBar" : "aboveBar" }),
      ...(sg.size || !recent ? { size: sg.size ?? 0.6 } : {}) });
    for (const it of this.ind) {
      const list = [], sub = it.pane !== 0, line = sub ? it.last.plots.find((pl) => pl.type !== "signals")?.data : null;
      it.last.plots.forEach((pl) => {
        if (pl.type !== "signals") return;
        const idx = pl.data.map((sg, i) => sg && c[i] && (!line || line[i] != null) ? i : -1).filter((i) => i >= 0);
        idx.forEach((i, k) => list.push(toMk(pl.data[i], i, k >= idx.length - KEEP, line)));
      });
      if (it.pane === 0) { main.push(...list); continue; }
      const host = it.series.find(Boolean);
      if (!host) continue;
      if (!it.markers && list.length) it.markers = LC.createSeriesMarkers(host, []);
      it.markers?.setMarkers(list);
    }
    this.sigMarkers = main;
    this._pushMarkers();
  }

  // 볼륨 프로파일: 화면에 보이는 봉만으로 계산해서 오른쪽에 가로 막대로
  _drawVP(ctx, size) {
    const it = this.ind.find((x) => x.profile);
    const range = this.chart.timeScale().getVisibleLogicalRange();
    if (!it || !range || !this.candles.length) { this.vp = null; return; }
    const vis = this.candles.slice(Math.max(0, Math.floor(range.from)), Math.min(this.candles.length, Math.ceil(range.to) + 1));
    const vp = this.vp = volumeProfile(vis, Math.max(6, Math.min(120, +it.params.rows || 30)), +it.params.va || 70);
    if (!vp) return;
    const maxW = size.width * Math.min(0.6, (+it.params.width || 28) / 100), right = size.width;
    for (const b of vp.bins) {
      const y1 = this.candle.priceToCoordinate(b.hi), y2 = this.candle.priceToCoordinate(b.lo);
      if (y1 == null || y2 == null) continue;
      const h = Math.max(1, y2 - y1 - 1), wb = maxW * b.buy / vp.max, ws = maxW * b.sell / vp.max, a = b.va ? 0.42 : 0.18;
      ctx.fillStyle = `rgba(34,176,125,${a})`; ctx.fillRect(right - wb - ws, y1, wb, h);
      ctx.fillStyle = `rgba(229,72,77,${a})`; ctx.fillRect(right - ws, y1, ws, h);
    }
    const py = this.candle.priceToCoordinate(vp.poc);
    if (py != null) { ctx.strokeStyle = "rgba(245,165,36,.85)"; ctx.setLineDash([4, 3]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(size.width, py); ctx.stroke(); ctx.setLineDash([]); }
  }

  // ------------------------------------------------------------ 오버레이
  async refreshOverlays() {
    const o = this.opts.overlays, sym = this.symbol, iv = this.interval;
    const got = { heat: null, whales: null, markers: null, sr: null };
    const jobs = [];
    if (o.heat) jobs.push(api(`/api/liq-heatmap?symbol=${sym}&interval=${iv}&limit=500`).then((h) => {
      const v = h.columns.flatMap(([, col]) => col.map(([, x]) => x)).sort((a, b) => a - b);
      h.norm = v[Math.floor(v.length * 0.995)] || 1;
      h.byTime = new Map(h.columns.map(([t, col]) => [t, col]));
      got.heat = h;
    }).catch(() => {}));
    if (o.whales) jobs.push(api(`/api/whales?symbol=${sym}&interval=${iv}&limit=1000${this.opts.whaleMin ? "&min_usd=" + this.opts.whaleMin : ""}`)
      .then((w) => (got.whales = w)).catch(() => {}));
    jobs.push(api(`/api/paper/markers?symbol=${sym}`).then((m) => (got.markers = { ...m, symbol: sym })).catch(() => {}));
    if (o.sr) jobs.push(api(`/api/levels?symbol=${sym}&interval=${iv}`).then((l) => (got.sr = l)).catch(() => {}));
    await Promise.all(jobs);
    if (!this._is(sym, iv)) return;   // 기다리는 동안 코인·봉을 바꿨으면 이전 결과는 버린다
    Object.assign(this, got);
    this._applyMarkers();
    this.heatLayer.update(); this.whaleLayer.update(); this.srLayer.update();
    this._legend();
  }

  setOverlay(name, on) { this.opts.overlays[name] = on; this.refreshOverlays(); }

  setScenario(sc, symbol = this.symbol) {
    this.scenario = symbol === this.symbol ? sc : null;
    this._applyMarkers();
  }

  _barTime(t) {
    const c = this.candles;
    let lo = 0, hi = c.length - 1;
    if (!c.length || t < c[0].time) return null;
    while (lo < hi) { const m = (lo + hi + 1) >> 1; if (c[m].time <= t) lo = m; else hi = m - 1; }
    return c[lo].time;
  }

  _applyMarkers() {
    this.priceLines.forEach((l) => this.candle.removePriceLine(l));
    this.priceLines = [];
    const mk = [], line = (price, title, color, style = 2) => price && this.priceLines.push(this.candle.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }));
    const m = this.markers?.symbol === this.symbol ? this.markers : null;
    if (this.opts.overlays.bots && m) {
      const add = (t, who) => {
        const et = this._barTime(t.entry_time), xt = this._barTime(t.exit_time), long = t.side === "long";
        if (et) mk.push({ time: et, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown", color: long ? css("--up") : css("--down"), text: `${who} ${long ? "롱" : "숏"}` });
        if (xt) mk.push({ time: xt, position: long ? "aboveBar" : "belowBar", shape: "circle", color: t.pnl > 0 ? css("--up") : css("--down"),
          text: `${t.pnl > 0 ? "익절" : "손절"} ${t.pnl > 0 ? "+" : ""}${fmt(t.pnl, 0)}` });
      };
      m.bots.forEach((b) => {
        b.trades.forEach((t) => add(t, "봇"));
        const p = b.position;
        if (p) {
          const et = this._barTime(p.entry_time);
          if (et) mk.push({ time: et, position: p.side === "long" ? "belowBar" : "aboveBar", shape: p.side === "long" ? "arrowUp" : "arrowDown", color: css("--accent"), text: `봇 ${p.side === "long" ? "롱" : "숏"} 보유` });
          line(p.entry_price, `${b.name.slice(0, 10)} 진입`, css("--accent"), 0); line(p.stop, "봇 손절", css("--down")); line(p.take, "봇 익절", css("--up")); line(p.liq_price, "봇 청산가", "rgba(229,72,77,.5)", 3);
        }
      });
      m.manual.trades.forEach((t) => add(t, "수동"));
    }
    this.editLines = {};
    const my = this._pos();
    if (my) {
      const et = this._barTime(my.entry_time);
      if (et) mk.push({ time: et, position: my.side === "long" ? "belowBar" : "aboveBar", shape: my.side === "long" ? "arrowUp" : "arrowDown", color: css("--info"), text: `내 ${my.side === "long" ? "롱" : "숏"}` });
      const mk2 = (price, title, color, style, width = 1) => this.candle.createPriceLine({ price, color, lineWidth: width, lineStyle: style, axisLabelVisible: true, title });
      this.editLines.entry = mk2(my.entry_price, this._entryTitle(), css("--info"), 0, 2);
      if (my.stop) this.editLines.stop = mk2(my.stop, this._slTitle("stop", my.stop), css("--down"), 2, 2);
      if (my.take) this.editLines.take = mk2(my.take, this._slTitle("take", my.take), css("--up"), 2, 2);
      this.editLines.liq = mk2(my.liq_price, "강제청산", "rgba(229,72,77,.55)", 3);
      Object.values(this.editLines).forEach((l) => this.priceLines.push(l));
    }
    const sc = this.scenario;
    if (this.opts.overlays.scenario && sc) {
      line(sc.entry, `${sc.title} 진입`, css("--accent"), 0); line(sc.stop, "시나리오 손절", css("--down"));
      sc.targets.forEach((t, i) => line(t, `목표${i + 1}`, css("--up")));
      if (sc.alt) { line(sc.alt.entry, "상단 숏", css("--accent"), 0); line(sc.alt.stop, "숏 손절", css("--down")); }
    }
    this.userLines.forEach((u) => this.priceLines.push(this.candle.createPriceLine({ price: u, color: "#a4acb6", lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: "" })));
    this._baseMarkers = mk;
    this._pushMarkers();
  }

  _pushMarkers() {
    const mk = [...(this._baseMarkers || []), ...(this.sigMarkers || [])];
    mk.sort((a, b) => a.time - b.time);
    this.markerApi.setMarkers(mk);
  }

  _drawHeat(ctx, size, p) {
    const h = this.heat;
    if (!h) return;
    const ts = this.chart.timeScale(), bw = Math.max(1, ts.options().barSpacing), rgb = css("--heat");
    const range = ts.getVisibleLogicalRange();
    if (!range) return;
    const c = this.candles;
    for (let i = Math.max(0, Math.floor(range.from) - 1); i <= Math.min(c.length - 1, Math.ceil(range.to) + 1); i++) {
      const col = h.byTime.get(c[i].time);
      if (!col) continue;
      const x = ts.timeToCoordinate(c[i].time);
      if (x == null) continue;
      for (const [bi, v] of col) {
        const a = Math.min(1, (v / h.norm) ** 1.6);
        if (a < 0.1) continue;
        const lo = h.price_min + bi * h.price_step;
        const y1 = this.candle.priceToCoordinate(lo + h.price_step), y2 = this.candle.priceToCoordinate(lo);
        if (y1 == null || y2 == null) continue;
        ctx.fillStyle = `rgba(${rgb},${(0.9 * a).toFixed(3)})`;
        ctx.fillRect(x - bw / 2, y1, bw + 0.5, Math.max(1, y2 - y1));
      }
    }
  }

  _drawWhales(ctx, size) {
    const w = this.whales;
    if (!w) return;
    const ts = this.chart.timeScale();
    // 호가 벽: 오른쪽에서 뻗는 막대 + 가로 점선
    const maxWall = Math.max(1, ...w.walls.map((x) => x.usd));
    ctx.font = "10px " + getComputedStyle(document.body).fontFamily;
    for (const wall of w.walls) {
      const y = this.candle.priceToCoordinate(wall.price);
      if (y == null) continue;
      const col = wall.side === "bid" ? "34,176,125" : "229,72,77";
      const len = 40 + 120 * (wall.usd / maxWall);
      ctx.fillStyle = `rgba(${col},.35)`;
      ctx.fillRect(size.width - len, y - 3, len, 6);
      ctx.strokeStyle = `rgba(${col},.35)`; ctx.setLineDash([2, 4]); ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(size.width - len, y); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = `rgba(${col},1)`; ctx.textAlign = "right";
      ctx.fillText(`${wall.side === "bid" ? "매수벽" : "매도벽"} $${big(wall.usd)}`, size.width - len - 4, y - 5);
    }
    // 고래 체결 버블
    for (const t of w.trades) {
      const x = ts.timeToCoordinate(t.bar), y = this.candle.priceToCoordinate(t.price);
      if (x == null || y == null) continue;
      const r = Math.min(16, 2.5 + 3 * Math.sqrt(t.usd / w.min_usd));
      const col = t.side === "buy" ? "34,176,125" : "229,72,77";
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${col},.22)`; ctx.fill();
      ctx.lineWidth = 1; ctx.strokeStyle = `rgba(${col},.85)`; ctx.stroke();
      if (r > 12) { ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.fillText(big(t.usd), x, y + 3); }
    }
  }

  _drawTrends(ctx) {
    const ts = this.chart.timeScale();
    const pts = [...this.trends, ...(this.pending ? [{ ...this.pending, t2: this.pending.t1, p2: this.pending.p1 }] : [])];
    ctx.lineWidth = 1.5; ctx.strokeStyle = "#e6e8ea";
    for (const d of pts) {
      const x1 = ts.timeToCoordinate(d.t1), x2 = ts.timeToCoordinate(d.t2);
      const y1 = this.candle.priceToCoordinate(d.p1), y2 = this.candle.priceToCoordinate(d.p2);
      if ([x1, x2, y1, y2].includes(null)) continue;
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      [[x1, y1], [x2, y2]].forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y, 2.5, 0, Math.PI * 2); ctx.fillStyle = "#e6e8ea"; ctx.fill(); });
    }
  }

  _autoscale(original) {
    const r = this.chart?.timeScale().getVisibleLogicalRange(), c = this.candles;
    if (!r || !c?.length) return original();
    let lo = Infinity, hi = -Infinity;
    for (let i = Math.max(0, Math.floor(r.from)); i <= Math.min(c.length - 1, Math.ceil(r.to)); i++) { lo = Math.min(lo, c[i].low); hi = Math.max(hi, c[i].high); }
    if (!Number.isFinite(lo)) return original();
    const p = this._pos();
    if (p) [p.entry_price, p.stop, p.take].forEach((v) => { if (v) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
    return { priceRange: { minValue: lo, maxValue: hi } };
  }

  // ------------------------------------------------------------ 내 포지션 선 (끌어서 손절·익절 수정)
  _pos() { return this.markers?.symbol === this.symbol ? this.markers.manual?.position : null; }
  _entryTitle() {
    const p = this._pos(), last = this.candles.at(-1)?.close;
    if (!p || !last) return "내 포지션";
    const side = p.side === "long" ? 1 : -1, roe = side * (last / p.entry_price - 1) * (p.leverage || 1) * 100;
    return `내 ${p.side === "long" ? "롱" : "숏"} ${p.leverage || ""}x ${roe >= 0 ? "+" : ""}${roe.toFixed(2)}%`;
  }
  _slTitle(kind, price) {
    const p = this._pos();
    const d = p ? (price / p.entry_price - 1) * 100 : 0;
    return `${kind === "stop" ? "손절" : "익절"} ${d >= 0 ? "+" : ""}${d.toFixed(2)}% (끌어서 수정)`;
  }
  _setupDrag() {
    const box = this.el;
    const near = (e) => {
      const p = this._pos();
      if (!p || !this.opts.onEditPosition) return null;
      const r = box.getBoundingClientRect(), y = e.clientY - r.top, x = e.clientX - r.left;
      if (x > r.width - this.chart.priceScale("right").width()) return null;
      for (const k of ["stop", "take"]) {
        const v = p[k];
        if (v == null) continue;
        const yy = this.candle.priceToCoordinate(v);
        if (yy != null && Math.abs(yy - y) <= 6) return k;
      }
      return null;
    };
    box.addEventListener("pointermove", (e) => {
      if (this._drag) {
        const r = box.getBoundingClientRect(), price = this.candle.coordinateToPrice(e.clientY - r.top);
        if (price == null) return;
        this._drag.price = price;
        this.editLines[this._drag.kind]?.applyOptions({ price, title: this._slTitle(this._drag.kind, price) });
        return;
      }
      if (!this.drawMode) box.style.cursor = near(e) ? "ns-resize" : "";
    }, true);
    const start = (e) => {
      const k = !this.drawMode && near(e);
      if (!k) return;
      e.stopPropagation(); e.preventDefault();
      this._drag = { kind: k, price: this._pos()[k] };
      this.chart.applyOptions({ handleScroll: false, handleScale: false });
    };
    box.addEventListener("pointerdown", start, true);
    box.addEventListener("mousedown", (e) => this._drag && e.stopPropagation(), true);
    window.addEventListener("pointerup", async () => {
      const d = this._drag;
      if (!d) return;
      this._drag = null; this._justDragged = true; setTimeout(() => (this._justDragged = false), 50);
      this.chart.applyOptions({ handleScroll: true, handleScale: true });
      const p = this._pos();
      const edit = { stop: p.stop, take: p.take, [d.kind]: d.price };
      try { await this.opts.onEditPosition(this.symbol, edit); } catch { /* 콜백에서 알림 */ }
      this.refreshOverlays();
    });
  }

  // ------------------------------------------------------------ 자동 지지·저항
  _drawSR(ctx, size) {
    const sr = this.sr;
    if (!sr) return;
    const ts = this.chart.timeScale();
    ctx.font = "10px " + getComputedStyle(document.body).fontFamily;
    const plotW = size.width, used = [];
    for (const z of [...sr.zones].sort((a, b) => b.touches - a.touches)) {
      const y1 = this.candle.priceToCoordinate(z.high), y2 = this.candle.priceToCoordinate(z.low);
      if (y1 == null || y2 == null) continue;
      const col = z.side === "resistance" ? "229,72,77" : "34,176,125";
      const a = Math.min(0.2, 0.05 + z.touches * 0.025);
      ctx.fillStyle = `rgba(${col},${a})`;
      ctx.fillRect(0, y1, plotW, Math.max(2, y2 - y1));
      ctx.strokeStyle = `rgba(${col},.45)`; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, (y1 + y2) / 2); ctx.lineTo(plotW, (y1 + y2) / 2); ctx.stroke();
      const ly = y1 - 3;
      if (!used.some((u) => Math.abs(u - ly) < 12)) {   // 가까운 구간끼리 글자가 겹치지 않게
        used.push(ly);
        ctx.fillStyle = `rgba(${col},.95)`; ctx.textAlign = "left";
        ctx.fillText(`${z.side === "resistance" ? "저항" : "지지"} ${px(z.price)} · ${z.touches}회`, 6, ly);
      }
    }
    ctx.setLineDash([6, 4]); ctx.lineWidth = 1.5;
    for (const l of sr.trendlines) {
      const x1 = ts.timeToCoordinate(l.t1), x2 = ts.timeToCoordinate(l.t2);
      const y1 = this.candle.priceToCoordinate(l.p1), y2 = this.candle.priceToCoordinate(l.p2);
      if ([x1, x2, y1, y2].includes(null)) continue;
      ctx.strokeStyle = l.kind === "resistance" ? "rgba(229,72,77,.8)" : "rgba(34,176,125,.8)";
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      ctx.fillStyle = ctx.strokeStyle; ctx.textAlign = "right"; ctx.fillText(l.label, x2 - 4, y2 - 6);
    }
    ctx.setLineDash([]);
  }

  // ------------------------------------------------------------ 그리기 도구
  setDrawMode(mode) { this.drawMode = mode; this.pending = null; this.el.style.cursor = mode ? "crosshair" : ""; }
  _click(p) {
    if (!this.drawMode || !p.point || this._justDragged) return;
    const price = this.candle.coordinateToPrice(p.point.y);
    if (price == null) return;
    if (this.drawMode === "hline") { this.userLines.push(price); this._saveDrawings(); this._applyMarkers(); this.setDrawMode(null); this.opts.onDrawDone?.(); return; }
    if (this.drawMode === "trend" && p.time != null) {
      if (!this.pending) { this.pending = { t1: p.time, p1: price }; this.drawLayer.update(); return; }
      this.trends.push({ ...this.pending, t2: p.time, p2: price });
      this.pending = null; this._saveDrawings(); this.drawLayer.update(); this.setDrawMode(null); this.opts.onDrawDone?.();
    }
  }
  clearDrawings() { this.userLines = []; this.trends = []; this._saveDrawings(); this._applyMarkers(); this.drawLayer.update(); }
  _key() { return `ft.draw.${this.symbol}`; }
  _saveDrawings() { try { localStorage.setItem(this._key(), JSON.stringify({ h: this.userLines, t: this.trends })); } catch { /* 무시 */ } }
  _loadDrawings() {
    try { const d = JSON.parse(localStorage.getItem(this._key()) || "{}"); this.userLines = d.h || []; this.trends = d.t || []; } catch { this.userLines = []; this.trends = []; }
    this.drawLayer.update();
  }

  // ------------------------------------------------------------ 범례
  _legend(p) {
    const c = this.candles;
    if (!c.length) { this.legendEl.innerHTML = `<div style="top:4px"><b>${esc(this.symbol)}</b> <span class="down">데이터 없음</span></div>`; return; }
    let idx = c.length - 1;
    if (p?.time != null) { const k = c.findIndex((b) => b.time === p.time); if (k >= 0) idx = k; }
    const b = c[idx], prev = c[idx - 1] || b, chg = (b.close / prev.close - 1) * 100;
    const heights = this.chart.panes().map((pn) => pn.getHeight());
    const tops = heights.map((_, i) => heights.slice(0, i).reduce((s, h) => s + h + 1, 0));
    const val = (v) => v == null ? "–" : Math.abs(v) >= 1e6 ? big(v) : px(v);
    let html = `<div style="top:${tops[0] + 4}px"><b>${this.symbol}</b> <span class="muted">${IV_LABEL[this.interval] || this.interval}${this.source === "synthetic" ? " · 가상 데이터" : ""}</span>
      <span class="muted">시</span> ${px(b.open)} <span class="muted">고</span> ${px(b.high)} <span class="muted">저</span> ${px(b.low)} <span class="muted">종</span> ${px(b.close)}
      <span class="${chg >= 0 ? "up" : "down"}">${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%</span>`;
    const mainInd = this.ind.filter((it) => it.pane === 0);
    const vals = (it) => it.last.plots.filter((pl) => pl.type !== "signals" && pl.legend !== false).map((pl) => val(pl.data[idx])).join(" ");
    const extra = (it) => it.profile && this.vp ? ` <span class="muted">POC</span> ${px(this.vp.poc)} <span class="muted">가치영역</span> ${px(this.vp.val)}~${px(this.vp.vah)}`
      : it.last.note ? ` <span class="muted">${esc(it.last.note)}</span>` : "";
    if (mainInd.length) html += `<br>` + mainInd.map((it) => `<span style="color:${it.last.plots.find((pl) => pl.color)?.color || "inherit"}">${esc(INDICATORS[it.spec.key].name)}${paramStr(it.params)}</span> ${vals(it)}${extra(it)}`).join(" · ");
    if (this.heat) html += `<br><span class="muted">청산맵: ${this.heat.model === "coinglass" ? "CoinGlass" : this.heat.model === "estimate_oi" ? "OI 기반 추정" : "거래대금 기반 추정"}</span> <span class="scale"></span>`;
    if (this.whales) html += `<br><span class="muted">고래 체결 ≥ $${big(this.whales.min_usd)} · ${this.whales.trades.length}건${this.whales.source === "binance" && this.whales.collecting_since ? " (프로그램 실행 후 수집분)" : ""} · 호가벽 ${this.whales.walls.length}개</span>`;
    html += `</div>`;
    for (const it of this.ind.filter((x) => x.pane > 0)) {
      const top = tops[it.pane];
      if (top == null) continue;
      html += `<div style="top:${top + 3}px"><span class="dim">${esc(INDICATORS[it.spec.key].name)}${paramStr(it.params)}</span> ${it.last.plots.filter((pl) => pl.type !== "signals" && pl.legend !== false).map((pl) => `<span style="color:${pl.color || "inherit"}">${val(pl.data[idx])}</span>`).join(" ")}${it.last.note ? ` <span class="accent">${esc(it.last.note)}</span>` : ""}</div>`;
    }
    this.legendEl.innerHTML = html;
  }
}

const paramStr = (p) => { const v = Object.values(p || {}); return v.length ? ` <span class="muted">${v.join(",")}</span>` : ""; };

function toData(c, pl) {
  return c.map((b, i) => {
    const v = pl.data[i];
    if (v == null || Number.isNaN(v)) return { time: b.time };
    const d = { time: b.time, value: v };
    if (pl.colors?.[i]) d.color = pl.colors[i];
    return d;
  });
}

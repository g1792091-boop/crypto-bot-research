// 자체 차트 엔진 (lightweight-charts v5 + 자체 보조지표 + 오버레이)
import { INDICATORS } from "./ind.js";
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
      wickUpColor: css("--up"), wickDownColor: css("--down") });
    this.markerApi = LC.createSeriesMarkers(this.candle, []);
    this.heatLayer = new Layer((ctx, size, p) => this._drawHeat(ctx, size, p), "bottom");
    this.whaleLayer = new Layer((ctx, size, p) => this._drawWhales(ctx, size, p), "normal");
    this.drawLayer = new Layer((ctx, size, p) => this._drawTrends(ctx, size, p), "top");
    [this.heatLayer, this.whaleLayer, this.drawLayer].forEach((l) => this.candle.attachPrimitive(l));
    this.chart.subscribeCrosshairMove((p) => this._legend(p));
    this.chart.subscribeClick((p) => this._click(p));
  }

  destroy() { clearInterval(this._timer); this.chart.remove(); this.el.innerHTML = ""; }

  async load(symbol = this.symbol, interval = this.interval) {
    const changed = symbol !== this.symbol || interval !== this.interval || !this.candles.length;
    this.symbol = symbol; this.interval = interval;
    const d = await api(`/api/candles?symbol=${symbol}&interval=${interval}&limit=${interval === "1m" ? 1500 : 1000}`);
    if (symbol !== this.symbol || interval !== this.interval) return;
    this.source = d.source;
    this.candles = d.candles;
    this.candle.setData(this.candles);
    if (changed) { this.chart.timeScale().fitContent(); this.chart.timeScale().scrollToRealTime(); this._loadDrawings(); }
    await this._loadExt();
    this.renderIndicators();
    this.refreshOverlays();
    this._legend();
    clearInterval(this._timer);
    this._timer = setInterval(() => this._tick(), 3000);
  }

  async _tick() {
    if (document.hidden || !this.candles.length) return;
    let d;
    try { d = await api(`/api/candles?symbol=${this.symbol}&interval=${this.interval}&limit=3`); } catch { return; }
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
    this.opts.onTick?.(this.candles.at(-1));
  }

  // ------------------------------------------------------------ 보조지표
  async _loadExt() {
    const need = new Set(this.indicators.map((i) => INDICATORS[i.key]?.remote).filter(Boolean));
    const jobs = [];
    if (need.has("derivatives")) jobs.push(api(`/api/derivatives?symbol=${this.symbol}&interval=${this.interval}&limit=500`).then((d) => Object.assign(this.ext, d)).catch(() => {}));
    if (need.has("cbp")) jobs.push(api(`/api/coinbase-premium?symbol=${this.symbol}&interval=${this.interval}`).then((d) => (this.ext.series = d.series)).catch(() => (this.ext.series = [])));
    await Promise.all(jobs);
  }

  setIndicators(list) { this.indicators = list; this._loadExt().then(() => this.renderIndicators()); }

  renderIndicators(valuesOnly = false) {
    const c = this.candles;
    if (!c.length) return;
    if (valuesOnly && this.ind.length === this.indicators.length) {
      this.ind.forEach((it) => { const r = INDICATORS[it.spec.key].compute(c, it.params, this.ext); r.plots.forEach((pl, k) => it.series[k] && it.series[k].setData(toData(c, pl))); it.last = r; });
      return;
    }
    for (const it of this.ind) it.series.forEach((s) => this.chart.removeSeries(s));
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
        const common = { priceLineVisible: false, lastValueVisible: def.pane === "sub", title: "" };
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
      if (r.levels && series[0]) r.levels.forEach((lv) => series[0].createPriceLine({ price: lv, color: "rgba(164,172,182,.35)", lineWidth: 1, lineStyle: 2, axisLabelVisible: false }));
      this.ind.push({ spec, params, series, pane, last: r });
    }
    const panes = this.chart.panes();
    // 가격 창이 항상 절반 이상을 차지하도록
    panes.forEach((p, i) => p.setStretchFactor(i === 0 ? Math.max(2, panes.length - 1) : 1));
    this._legend();
  }

  // ------------------------------------------------------------ 오버레이
  async refreshOverlays() {
    const o = this.opts.overlays, sym = this.symbol, iv = this.interval;
    const jobs = [];
    if (o.heat) jobs.push(api(`/api/liq-heatmap?symbol=${sym}&interval=${iv}&limit=500`).then((h) => {
      const v = h.columns.flatMap(([, col]) => col.map(([, x]) => x)).sort((a, b) => a - b);
      h.norm = v[Math.floor(v.length * 0.995)] || 1;
      h.byTime = new Map(h.columns.map(([t, col]) => [t, col]));
      this.heat = h;
    }).catch(() => (this.heat = null)));
    else this.heat = null;
    if (o.whales) jobs.push(api(`/api/whales?symbol=${sym}&interval=${iv}&limit=1000${this.opts.whaleMin ? "&min_usd=" + this.opts.whaleMin : ""}`)
      .then((w) => (this.whales = w)).catch(() => (this.whales = null)));
    else this.whales = null;
    if (o.bots) jobs.push(api(`/api/paper/markers?symbol=${sym}`).then((m) => (this.markers = m)).catch(() => (this.markers = null)));
    else this.markers = null;
    await Promise.all(jobs);
    if (sym !== this.symbol || iv !== this.interval) return;
    this._applyMarkers();
    this.heatLayer.update(); this.whaleLayer.update();
    this._legend();
  }

  setOverlay(name, on) { this.opts.overlays[name] = on; this.refreshOverlays(); }

  setScenario(sc) { this.scenario = sc; this._applyMarkers(); }

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
    const m = this.markers;
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
      const p = m.manual.position;
      if (p) { line(p.entry_price, "내 포지션", css("--info"), 0); line(p.stop, "내 손절", css("--down")); line(p.take, "내 익절", css("--up")); line(p.liq_price, "내 청산가", "rgba(229,72,77,.5)", 3); }
    }
    const sc = this.scenario;
    if (this.opts.overlays.scenario && sc) {
      line(sc.entry, `${sc.title} 진입`, css("--accent"), 0); line(sc.stop, "시나리오 손절", css("--down"));
      sc.targets.forEach((t, i) => line(t, `목표${i + 1}`, css("--up")));
      if (sc.alt) { line(sc.alt.entry, "상단 숏", css("--accent"), 0); line(sc.alt.stop, "숏 손절", css("--down")); }
    }
    this.userLines.forEach((u) => this.priceLines.push(this.candle.createPriceLine({ price: u, color: "#a4acb6", lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: "" })));
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

  // ------------------------------------------------------------ 그리기 도구
  setDrawMode(mode) { this.drawMode = mode; this.pending = null; this.el.style.cursor = mode ? "crosshair" : ""; }
  _click(p) {
    if (!this.drawMode || !p.point) return;
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
    if (!c.length) return;
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
    if (mainInd.length) html += `<br>` + mainInd.map((it) => `<span style="color:${it.last.plots[0]?.color || "inherit"}">${esc(INDICATORS[it.spec.key].name)}${paramStr(it.params)}</span> ${it.last.plots.map((pl) => val(pl.data[idx])).join(" ")}`).join(" · ");
    if (this.heat) html += `<br><span class="muted">청산맵: ${this.heat.model === "coinglass" ? "CoinGlass" : this.heat.model === "estimate_oi" ? "OI 기반 추정" : "거래대금 기반 추정"}</span> <span class="scale"></span>`;
    if (this.whales) html += `<br><span class="muted">고래 체결 ≥ $${big(this.whales.min_usd)} · ${this.whales.trades.length}건${this.whales.source === "binance" && this.whales.collecting_since ? " (프로그램 실행 후 수집분)" : ""} · 호가벽 ${this.whales.walls.length}개</span>`;
    html += `</div>`;
    for (const it of this.ind.filter((x) => x.pane > 0)) {
      const top = tops[it.pane];
      if (top == null) continue;
      html += `<div style="top:${top + 3}px"><span class="dim">${esc(INDICATORS[it.spec.key].name)}${paramStr(it.params)}</span> ${it.last.plots.map((pl) => `<span style="color:${pl.color || "inherit"}">${val(pl.data[idx])}</span>`).join(" ")}${it.last.note ? ` <span class="accent">${esc(it.last.note)}</span>` : ""}</div>`;
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
    if (pl.type === "hist" && pl.colors?.[i]) d.color = pl.colors[i];
    return d;
  });
}

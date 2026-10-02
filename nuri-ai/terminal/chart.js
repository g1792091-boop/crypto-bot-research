// 누리 차트 터미널 — 차트 엔진 (lightweight-charts v5 + 보조지표 + 흐름 오버레이)
// 원본: GH Quant frontend/js/chart.js. 백엔드 api(...) 대신 ./data.js (trade.js · history.js · flow.js) 로 다시 연결했다.
// 오버레이 레이어(캔버스에 직접 그림, 차트와 같이 확대/이동): 호가 벽 · 고래 체결 · 청산 구간(추정) · 볼륨 프로파일 · 구름/밴드 채우기 · 상자/패턴
import { volumeProfile } from "./ind.js";
import { DEFS, paneOf, labelOf } from "./registry.js";
import * as D from "./data.js";

const LC = () => window.LightweightCharts;
export const COL = { up: "#089981", down: "#f23645", text: "#d1d4dc", text2: "#b2b5be", muted: "#787b86", line: "#2a2e39", bg: "#131722", accent: "#2962ff", heat: "255,152,0" };
const FONT = '"Pretendard Variable", Pretendard, "Noto Sans KR", system-ui, sans-serif';
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const big = (v) => { if (v == null || !Number.isFinite(+v)) return "–"; const a = Math.abs(v); return a >= 1e12 ? (v / 1e12).toFixed(2) + "T" : a >= 1e9 ? (v / 1e9).toFixed(2) + "B" : a >= 1e6 ? (v / 1e6).toFixed(2) + "M" : a >= 1e3 ? (v / 1e3).toFixed(1) + "K" : (+v).toFixed(a >= 10 ? 0 : 2); };
// 아래 창 지표 값 (크기에 맞게)
export const smart = (v) => { if (v == null || !Number.isFinite(v)) return "–"; const a = Math.abs(v); return a >= 1e6 ? big(v) : a >= 1000 ? v.toFixed(0) : a >= 100 ? v.toFixed(1) : a >= 1 ? v.toFixed(2) : a === 0 ? "0" : v.toPrecision(3); };
const SKIP = ["signals", "boxes", "profiles", "patterns", "fill"];

// 캔버스에 직접 그리는 레이어. 차트와 함께 확대/이동된다.
export class Layer {
  constructor(draw, z = "bottom") {
    this.draw = draw; this._z = z;
    // 한 레이어의 오류가 차트 전체 그리기를 멈추지 않게 감싼다
    const safe = (context, mediaSize) => { if (!this.p) return; context.save(); try { this.draw(context, mediaSize, this.p); } catch (e) { if (!this._warned) { this._warned = true; console.warn("[차트 레이어]", e); } } finally { context.restore(); } };
    this._view = { zOrder: () => this._z, renderer: () => ({ draw: (t) => t.useMediaCoordinateSpace(({ context, mediaSize }) => safe(context, mediaSize)) }) };
  }
  attached(p) { this.p = p; }
  detached() { this.p = null; }
  paneViews() { return [this._view]; }
  update() { this.p?.requestUpdate(); }
}

// 봉 마감까지 남은 시간
export function fmtLeft(sec) {
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60), x = sec % 60, z = (n) => String(n).padStart(2, "0");
  return d ? `${d}일 ${z(h)}:${z(m)}:${z(x)}` : h ? `${z(h)}:${z(m)}:${z(x)}` : `${z(m)}:${z(x)}`;
}
// 가격축의 현재가 라벨 바로 아래에 남은 시간 (트레이딩뷰 방식). 야후(장 시간이 있는 종목)는 표시 안 함
class Countdown {
  constructor(tc) {
    this.tc = tc; this.y = null; this.text = ""; this.bg = "#444";
    this._view = { coordinate: () => this.y ?? -100, text: () => this.text, textColor: () => "#fff", backColor: () => this.bg, visible: () => !!this.text, tickVisible: () => false };
  }
  attached(p) { this.p = p; }
  detached() { this.p = null; }
  updateAllViews() {
    const tc = this.tc, b = tc.candles.at(-1);
    if (!b || tc.exchange === "yahoo") { this.text = ""; return; }
    const y = tc.candle.priceToCoordinate(b.close);
    if (y == null) { this.text = ""; return; }
    this.y = y + 18;
    this.text = fmtLeft(b.time + (D.IV_SEC[tc.interval] || 3600) - Date.now() / 1000);
    this.bg = b.close >= b.open ? COL.up : COL.down;
  }
  priceAxisViews() { return [this._view]; }
  update() { this.p?.requestUpdate(); }
}

export class TermChart {
  // opts: {getInds(), overlays (공유 객체), ws (false 면 웹소켓 안 씀), onLegend(act, id), onLoad(tc), onFlow(tc), onStatus(tc), isActive()}
  constructor(el, opts = {}) {
    this.el = el; this.opts = opts;
    this.exchange = null; this.symbol = null; this.interval = null;
    this.candles = []; this.meta = {}; this.ind = []; this.flow = { snap: null, liq: null, whales: new Map(), err: "" };
    this.stratMarkers = []; this.sigMarkers = []; this.ctype = "candles"; this.prec = 2; this.live = "";
    el.innerHTML = `<div class="nt-chart"></div><div class="nt-legend"></div><div class="nt-msg" hidden></div>`;
    this.legendEl = el.querySelector(".nt-legend"); this.msgEl = el.querySelector(".nt-msg");
    this.legendEl.addEventListener("click", (e) => {      // 범례의 지표 숨기기 · 설정 · 지우기 (트레이딩뷰 방식)
      if (e.target.closest(".lg-head")) { this.legendEl.classList.toggle("open"); return; }   // 휴대폰: 지표 줄 펼치기/접기
      const b = e.target.closest("[data-lg]");
      if (b) { e.stopPropagation(); this.opts.onLegend?.(b.dataset.lg, b.dataset.id, this); }
    });
    const L = LC();
    this.chart = L.createChart(el.querySelector(".nt-chart"), {
      autoSize: true,
      layout: { background: { type: "solid", color: COL.bg }, textColor: COL.text2, fontSize: 11, attributionLogo: false, fontFamily: FONT,
        panes: { separatorColor: COL.line, separatorHoverColor: "rgba(41,98,255,.35)" } },
      grid: { vertLines: { color: "rgba(42,46,57,.55)" }, horzLines: { color: "rgba(42,46,57,.55)" } },
      rightPriceScale: { borderColor: COL.line, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: COL.line, timeVisible: true, secondsVisible: false, rightOffset: 8 },
      crosshair: { mode: L.CrosshairMode.Normal, vertLine: { color: "#787b86", width: 1, style: 3, labelBackgroundColor: "#363a45" }, horzLine: { color: "#787b86", width: 1, style: 3, labelBackgroundColor: "#363a45" } },
      localization: { locale: "ko-KR", timeFormatter: (t) => this._fmtTime(t) },
    });
    this.candle = this.chart.addSeries(L.CandlestickSeries, { upColor: COL.up, downColor: COL.down, borderVisible: false, wickUpColor: COL.up, wickDownColor: COL.down,
      autoscaleInfoProvider: (original) => this._autoscale(original) });
    this.markerApi = L.createSeriesMarkers(this.candle, []);
    this.fillLayer = new Layer((ctx, size) => this._drawFills(ctx, size), "bottom");
    this.vpLayer = new Layer((ctx, size) => this._drawVP(ctx, size), "bottom");
    this.boxLayer = new Layer((ctx, size) => this._drawBoxes(ctx, size), "bottom");
    this.liqLayer = new Layer((ctx, size) => this._drawLiq(ctx, size), "bottom");
    this.wallLayer = new Layer((ctx, size) => this._drawWalls(ctx, size), "bottom");
    this.whaleLayer = new Layer((ctx, size) => this._drawWhales(ctx, size), "normal");
    this.aiLayer = new Layer((ctx, size) => this._drawAi(ctx, size), "normal");   // AI 팀 분석: 패턴 선
    this.ai = { segs: [] }; this.aiLines = []; this.aiMarkers = [];
    this.countdown = new Countdown(this);
    [this.fillLayer, this.vpLayer, this.boxLayer, this.liqLayer, this.wallLayer, this.whaleLayer, this.aiLayer, this.countdown].forEach((l) => this.candle.attachPrimitive(l));
    this._cdTimer = setInterval(() => !document.hidden && this.countdown.update(), 1000);
    this.chart.subscribeCrosshairMove((p) => { this._lastCross = p; this._legend(p); });
    // 칸 크기·창 높이가 바뀌면 아래 창 범례 위치를 다시 잡는다
    this._ro = new ResizeObserver(() => this._legendSoon());
    this._ro.observe(el);
  }
  _legendSoon() { if (this._lgRaf) return; this._lgRaf = requestAnimationFrame(() => { this._lgRaf = 0; this._legend(this._lastCross); }); }

  destroy() {
    this._stopLive(); clearInterval(this._cdTimer); clearInterval(this._flowTimer); clearInterval(this._liqTimer); this._ro?.disconnect();
    try { this.chart.remove(); } catch (e) { /* 무시 */ }
    this.el.innerHTML = "";
  }
  _is(ex, sym, iv) { return ex === this.exchange && sym === this.symbol && iv === this.interval; }
  _fmtTime(t) {
    const d = new Date(t * 1000 + 9 * 3600e3), z = (n) => String(n).padStart(2, "0");   // 한국 시간
    const day = `${String(d.getUTCFullYear()).slice(2)}.${z(d.getUTCMonth() + 1)}.${z(d.getUTCDate())}`;
    return (D.IV_SEC[this.interval] || 3600) >= 86400 ? day : `${day} ${z(d.getUTCHours())}:${z(d.getUTCMinutes())}`;
  }
  // 가격 자릿수
  px(v) { return v == null || !Number.isFinite(v) ? "–" : v.toLocaleString("en-US", { minimumFractionDigits: this.prec, maximumFractionDigits: this.prec }); }
  _applyPrec() {
    const last = this.candles.at(-1)?.close || 0, cur = this.meta.currency;
    // 최근 봉들의 소수 자릿수를 보고 정한다 (호가 단위와 비슷하게)
    const dec = (x) => { const s = String(x); const i = s.indexOf("."); return i < 0 || /e/.test(s) ? 0 : Math.min(8, s.length - i - 1); };
    let seen = 0; for (const b of this.candles.slice(-60)) seen = Math.max(seen, dec(b.close), dec(b.open));
    const cap = cur === "KRW" ? (last >= 100 ? 0 : last >= 1 ? 2 : 4) : last >= 10000 ? 2 : last >= 100 ? 2 : last >= 1 ? 4 : last >= 0.01 ? 6 : 8;
    this.prec = Math.max(last < 1 ? 4 : 0, Math.min(cap, seen));
    const pf = { type: "price", precision: this.prec, minMove: 10 ** -this.prec };
    this.candle.applyOptions({ priceFormat: pf });
    this.disp?.applyOptions({ priceFormat: pf });
  }
  msg(text) { this.msgEl.hidden = !text; this.msgEl.textContent = text || ""; }

  // ------------------------------------------------------------ 데이터
  async load(exchange = this.exchange, symbol = this.symbol, interval = this.interval) {
    const changed = !this._is(exchange, symbol, interval) || !this.candles.length;
    const sym0 = this.symbol, ex0 = this.exchange;
    this.exchange = exchange; this.symbol = symbol; this.interval = interval;
    const seq = this._seq = (this._seq || 0) + 1;
    this._stopLive();
    if (changed) {
      if (sym0 !== symbol || ex0 !== exchange) { this.flow = { snap: null, liq: null, whales: new Map(), err: "" }; this.stratMarkers = []; }
      [this.wallLayer, this.whaleLayer, this.liqLayer].forEach((l) => l.update());
    }
    this.full = false; this.fullNote = "";
    this.msg("불러오는 중…"); this._legend();
    let r;
    try { r = await D.loadCandles({ exchange, symbol, interval }); }
    catch (e) {
      if (seq === this._seq) {
        this.candles = []; this.candle.setData([]); this.disp?.setData([]);
        this.ind.forEach((it) => it.series.forEach((s) => s?.setData([])));
        this.sigMarkers = []; this._pushMarkers(); this._legend();
        this.msg(`${symbol}: ${e.message || e}`);
      }
      throw e;
    }
    if (seq !== this._seq) return;
    this.msg("");
    this.meta = r.meta; this.candles = r.candles;
    this._applyPrec(); this._display();
    if (changed) this.showBars(180);
    this.renderIndicators();
    this._legend();
    this._startLive();
    this.refreshFlow();
    this.opts.onLoad?.(this);
  }

  // 전체 과거 (history.js)
  async loadFull(onProgress) {
    const ex = this.exchange, sym = this.symbol, iv = this.interval, seq = this._seq;
    const r = await D.fullHistory({ exchange: ex, symbol: sym, interval: iv, resolved: this.meta.resolved }, onProgress);
    if (seq !== this._seq || !this._is(ex, sym, iv)) return null;
    // 지금 받은 최신 봉들과 합친다 (전체 과거 쪽이 조금 늦을 수 있음)
    const last = r.candles.at(-1)?.time ?? 0;
    this.candles = D.clean([...r.candles, ...this.candles.filter((b) => b.time > last)]);
    this.full = true; this.fullNote = r.note;
    this._applyPrec(); this._display();
    this.renderIndicators(); this._legend();
    this.chart.timeScale().fitContent();
    this.opts.onLoad?.(this);
    return r;
  }

  _startLive() {
    this._stopLive();
    const ex = this.exchange, sym = this.symbol, iv = this.interval;
    const poll = (ms) => { clearInterval(this._timer); this._timer = setInterval(() => this._tick(), ms); };
    const restMs = ex === "yahoo" ? 30000 : ex === "upbit" ? 5000 : 4000;
    this.live = ex === "yahoo" ? "30초 갱신" : "폴링";
    poll(restMs);
    if (this.opts.ws !== false && (ex === "binancef" || ex === "binance")) {
      this.ws = D.klineSocket({ exchange: ex, symbol: sym, interval: iv }, (bar) => {
        if (!this._is(ex, sym, iv)) return;
        const last = this.candles.at(-1);
        // 다른 시세 출처(가짜·지연 데이터)와 20% 넘게 다르면 쓰지 않는다
        if (last && Math.abs(bar.close / last.close - 1) > 0.2) { this.ws?.close(); this.ws = null; this.live = "폴링"; poll(restMs); this.opts.onStatus?.(this); return; }
        if (this.live !== "실시간") { this.live = "실시간"; poll(20000); this.opts.onStatus?.(this); }
        this._merge([bar], true);
      }, () => { if (this._is(ex, sym, iv)) { this.ws = null; this.live = "폴링"; poll(restMs); this.opts.onStatus?.(this); } });
    }
    this.opts.onStatus?.(this);
  }
  _stopLive() { clearInterval(this._timer); this._timer = null; this.ws?.close(); this.ws = null; }

  async _tick() {
    if (document.hidden || !this.candles.length) return;
    const ex = this.exchange, sym = this.symbol, iv = this.interval;
    let bars;
    try { bars = await D.latestBars({ exchange: ex, symbol: sym, interval: iv }); } catch (e) { return; }
    if (!this._is(ex, sym, iv)) return;   // 그 사이 종목을 바꿨으면 버린다
    this._merge(bars);
  }
  // 새 봉 합치기 (반 봉보다 가까운 시각은 같은 봉 — 야후의 진행 중 봉 시각 차이)
  _merge(bars, fromWs = false) {
    const step = D.IV_SEC[this.interval] || 3600;
    let newBar = false, changed = false;
    for (const b of bars) {
      const last = this.candles.at(-1);
      if (!last) break;
      if (Math.abs(b.time - last.time) < step / 2) { this.candles[this.candles.length - 1] = { ...b, time: last.time }; changed = true; }
      else if (b.time > last.time) { this.candles.push(b); newBar = changed = true; }
    }
    if (!changed) return;
    if (this.ctype === "candles" || this.ctype === "hollow") this.candle.update(this.candles.at(-1));
    else this._display();
    if (this.disp && (this.ctype === "line" || this.ctype === "area" || this.ctype === "bars")) { /* _display 에서 처리 */ }
    const now = Date.now();
    if (newBar) this.renderIndicators(true);
    else if (now - (this._indAt || 0) > (fromWs ? 5000 : 8000)) this.renderIndicators(true);
    this._legend();
    this.opts.onTick?.(this);
  }

  // ------------------------------------------------------------ 보조지표
  renderIndicators(valuesOnly = false) {
    const c = this.candles, L = LC(), specs = this.opts.getInds?.() || [];
    this._indAt = Date.now();
    if (!c.length) return;
    const ctxOf = (spec) => ({ id: spec.id, color: spec.color, ext: {}, extra: { symbol: this.symbol, exchange: this.exchange, interval: this.interval },
      onAsync: () => this._is(this.exchange, this.symbol, this.interval) && this.renderIndicators() });
    const run = (spec, def, params) => { try { return def.compute(c, params, ctxOf(spec)) || { plots: [] }; } catch (e) { return { plots: [], note: "계산 오류: " + (e.message || e) }; } };
    const sameShape = valuesOnly && this.ind.length === specs.length && this.ind.every((it, i) => it.spec === specs[i]);
    if (sameShape) {
      for (const it of this.ind) {
        const r = run(it.spec, it.def, it.params);
        if (r.plots.filter((p) => !SKIP.includes(p.type)).length !== it.series.filter(Boolean).length) { return this.renderIndicators(false); }
        r.plots.forEach((pl, k) => it.series[k] && it.series[k].setData(toData(c, pl)));
        it.last = r;
      }
      this._applySignals(); this.boxLayer.update(); this.fillLayer.update(); this.vpLayer.update();
      return;
    }
    for (const it of this.ind) { it.markers?.detach(); it.series.forEach((s) => { try { s && this.chart.removeSeries(s); } catch (e) { /* 무시 */ } }); }
    this.ind = [];
    while (this.chart.panes().length > 1) { try { this.chart.removePane(this.chart.panes().length - 1); } catch (e) { break; } }
    let paneNo = 0;
    for (const spec of specs) {
      const def = DEFS[spec.key];
      if (!def) continue;
      const params = { ...def.params, ...spec.params }, where = paneOf(spec);
      const r = run(spec, def, params);
      const pane = where === "sub" ? ++paneNo : 0;
      const subFmt = { type: "custom", formatter: smart, minMove: 1e-8 };
      const series = r.plots.map((pl) => {
        if (SKIP.includes(pl.type)) return null;
        const common = { priceLineVisible: false, lastValueVisible: where === "sub" && pl.legend !== false, title: "", ...(where === "sub" ? { priceFormat: subFmt } : { priceFormat: { type: "price", precision: this.prec, minMove: 10 ** -this.prec } }) };
        let s;
        if (pl.type === "hist") s = this.chart.addSeries(L.HistogramSeries, { ...common, ...(where === "volume" ? { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false } : {}) }, pane);
        else s = this.chart.addSeries(L.LineSeries, { ...common, color: pl.color || spec.color, lineWidth: pl.lineWidth ?? 2, lineStyle: pl.lineStyle ?? 0,
          crosshairMarkerVisible: false, ...(pl.type === "dots" ? { lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 1.6 } : {}),
          ...(where === "volume" ? { priceScaleId: "vol" } : {}) }, pane);
        s.setData(toData(c, pl));
        if (spec.hidden) s.applyOptions({ visible: false });
        return s;
      });
      if (where === "volume") this.chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      const first = series.find(Boolean);
      if (r.levels && first) r.levels.forEach((lv) => first.createPriceLine({ price: lv, color: "rgba(164,172,182,.35)", lineWidth: 1, lineStyle: 2, axisLabelVisible: false }));
      this.ind.push({ spec, def, params, series, pane, last: r, profile: !!def.profile });
    }
    this._applySignals();
    this.vpLayer.update(); this.boxLayer.update(); this.fillLayer.update();
    const panes = this.chart.panes();
    panes.forEach((p, i) => p.setStretchFactor(i === 0 ? Math.max(2.2, panes.length - 0.5) : 1));   // 가격 창이 항상 절반 이상
    this._scaleModes();
    this._legend(); this._legendSoon();
  }

  // 지표 신호 → 마커. 가격 위 지표는 캔들에, 아래 창 지표는 그 지표선에 붙인다
  _applySignals() {
    const c = this.candles, main = [], L = LC(), KEEP = 12;
    const toMk = (sg, i, recent, line) => ({ time: c[i].time, shape: sg.shape || (sg.dir > 0 ? "arrowUp" : "arrowDown"),
      color: sg.color || (sg.dir > 0 ? COL.up : COL.down), text: recent ? sg.text || "" : "",
      ...(line ? { position: sg.dir > 0 ? "atPriceBottom" : "atPriceTop", price: line[i] } : { position: sg.dir > 0 ? "belowBar" : "aboveBar" }),
      ...(sg.size || !recent ? { size: sg.size ?? 0.6 } : {}) });
    for (const it of this.ind) {
      if (it.spec.hidden) { it.markers?.setMarkers([]); continue; }
      const list = [], sub = it.pane !== 0, line = sub ? it.last.plots.find((pl) => !SKIP.includes(pl.type))?.data : null;
      it.last.plots.forEach((pl) => {
        if (pl.type !== "signals") return;
        const idx = pl.data.map((sg, i) => sg && c[i] && (!line || line[i] != null) ? i : -1).filter((i) => i >= 0);
        idx.forEach((i, k) => list.push(toMk(pl.data[i], i, k >= idx.length - KEEP, line)));
      });
      if (it.pane === 0) { main.push(...list); continue; }
      const host = it.series.find(Boolean);
      if (!host) continue;
      if (!it.markers && list.length) it.markers = L.createSeriesMarkers(host, []);
      it.markers?.setMarkers(list);
    }
    this.sigMarkers = main;
    this._pushMarkers();
  }
  setStrategyMarkers(list) { this.stratMarkers = list || []; this._pushMarkers(); }
  // AI 팀 분석 겹쳐 그리기: lines(가격선 · 가격축 이름표) · markers(봉 위 표시) · segs(패턴 선)
  setAiOverlay({ lines = [], markers = [], segs = [] } = {}) {
    for (const pl of this.aiLines) { try { this.candle.removePriceLine(pl); } catch (e) { /* 이미 없음 */ } }
    this.aiLines = [];
    for (const l of lines) {
      if (!Number.isFinite(+l.price) || +l.price <= 0) continue;
      try { this.aiLines.push(this.candle.createPriceLine({ price: +l.price, color: l.color || "#ab47bc", lineWidth: 1, lineStyle: l.style ?? 2, axisLabelVisible: true, title: String(l.label || "").slice(0, 22) })); } catch (e) { /* 무시 */ }
    }
    const c = this.candles, step = D.IV_SEC[this.interval] || 3600;
    this.aiMarkers = markers.map((m) => {
      const sec = Math.floor(m.t / 1000); if (!c.length || sec < c[0].time || sec > c.at(-1).time + step) return null;
      const time = this._barTime(sec); if (time == null) return null;
      const dir = m.dir || 0;
      return { time, position: dir > 0 ? "belowBar" : dir < 0 ? "aboveBar" : "inBar", shape: dir > 0 ? "arrowUp" : dir < 0 ? "arrowDown" : "square", color: m.color || "#ab47bc", text: String(m.text || "").slice(0, 16), size: dir ? 1 : 0.6 };
    }).filter(Boolean);
    this.ai.segs = segs || [];
    this._pushMarkers(); this.aiLayer.update();
  }
  _drawAi(ctx) {
    const segs = this.ai.segs; if (!segs?.length || !this.candles.length) return;
    const ts = this.chart.timeScale(), step = D.IV_SEC[this.interval] || 3600, c = this.candles;
    const xOf = (t) => { const sec = Math.floor(t / 1000); if (sec > c.at(-1).time) { const lx = ts.timeToCoordinate(c.at(-1).time); return lx == null ? null : lx + (sec - c.at(-1).time) / step * (ts.options().barSpacing || 6); } const b = this._barTime(sec); return b == null ? null : ts.timeToCoordinate(b); };
    ctx.font = "10px " + FONT; ctx.lineWidth = 1.6;
    for (const s of segs) {
      const x1 = xOf(s.a.t), x2 = xOf(s.b.t), y1 = this.candle.priceToCoordinate(s.a.p), y2 = this.candle.priceToCoordinate(s.b.p);
      if ([x1, x2, y1, y2].some((v) => v == null)) continue;
      ctx.strokeStyle = s.color || "#ffb300"; ctx.setLineDash([6, 3]);
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      if (s.label) { ctx.setLineDash([]); ctx.fillStyle = s.color || "#ffb300"; ctx.fillText(String(s.label).slice(0, 24), Math.min(x1, x2) + 4, Math.min(y1, y2) - 4); }
    }
    ctx.setLineDash([]);
  }
  _pushMarkers() {
    const mk = [...(this.sigMarkers || []), ...(this.stratMarkers || []), ...(this.aiMarkers || [])];
    mk.sort((a, b) => a.time - b.time);
    try { this.markerApi.setMarkers(mk); } catch (e) { /* 봉이 바뀌는 중 */ }
  }

  // 구름(일목) · 밴드 채우기
  _drawFills(ctx) {
    const c = this.candles, ts = this.chart.timeScale(), r = ts.getVisibleLogicalRange();
    if (!r || !c.length) return;
    const i0 = Math.max(1, Math.floor(r.from) - 1), i1 = Math.min(c.length - 1, Math.ceil(r.to) + 1);
    for (const it of this.ind) {
      if (it.pane !== 0 || it.spec.hidden) continue;
      for (const pl of it.last.plots) {
        if (pl.type !== "fill" || !pl.a || !pl.b) continue;
        for (let i = i0; i <= i1; i++) {
          const a0 = pl.a[i - 1], b0 = pl.b[i - 1], a1 = pl.a[i], b1 = pl.b[i];
          if (a0 == null || b0 == null || a1 == null || b1 == null) continue;
          const x0 = ts.logicalToCoordinate(i - 1), x1 = ts.logicalToCoordinate(i);
          const ya0 = this.candle.priceToCoordinate(a0), yb0 = this.candle.priceToCoordinate(b0), ya1 = this.candle.priceToCoordinate(a1), yb1 = this.candle.priceToCoordinate(b1);
          if ([x0, x1, ya0, yb0, ya1, yb1].includes(null)) continue;
          ctx.fillStyle = pl.color || (a1 >= b1 ? pl.up : pl.dn);
          ctx.beginPath(); ctx.moveTo(x0, ya0); ctx.lineTo(x1, ya1); ctx.lineTo(x1, yb1); ctx.lineTo(x0, yb0); ctx.closePath(); ctx.fill();
        }
      }
    }
  }

  // FVG · 오더블록 같은 가격 구간 상자 · 세션 프로파일 · 차트 패턴
  _drawBoxes(ctx, size) {
    const c = this.candles, ts = this.chart.timeScale();
    if (!c.length) return;
    ctx.font = "10px " + FONT;
    for (const it of this.ind) {
      if (it.pane !== 0 || it.spec.hidden) continue;
      for (const pl of it.last.plots) {
        if (pl.type === "profiles") { this._drawProfiles(ctx, size, pl.sessions); continue; }
        if (pl.type === "patterns") { this._drawPatterns(ctx, size, pl.patterns); continue; }
        if (pl.type !== "boxes") continue;
        for (const b of pl.boxes) {
          const x0 = ts.logicalToCoordinate(b.i0), x1 = b.i1 == null ? size.width : ts.logicalToCoordinate(b.i1);
          const y0 = this.candle.priceToCoordinate(b.top), y1 = this.candle.priceToCoordinate(b.bottom);
          if (x0 == null || x1 == null || y0 == null || y1 == null || x1 < 0 || x0 > size.width) continue;
          ctx.fillStyle = b.color; ctx.fillRect(x0, y0, Math.max(1, x1 - x0), Math.max(1, y1 - y0));
          if (b.label && x1 - x0 > 34 && y1 - y0 > 9) { ctx.fillStyle = "rgba(230,232,234,.55)"; ctx.fillText(b.label, Math.max(2, x0 + 3), y0 + 10); }
        }
      }
    }
  }
  _drawPatterns(ctx, size, pats) {
    const ts = this.chart.timeScale(), s = this.candle, X = (i) => ts.logicalToCoordinate(i), Y = (v) => s.priceToCoordinate(v), used = [];
    const free = (x, y, w, h) => { if (used.some((r) => x < r.x + r.w && x + w > r.x && y < r.y + r.h && y + h > r.y)) return false; used.push({ x, y, w, h }); return true; };
    [...pats].reverse().forEach((pt, rank) => {
      const xa = X(pt.i0), xb = X(pt.j);
      if (xa == null || xb == null || xb < -80 || xa > size.width + 80) return;
      const small = xb - xa < 36;
      const col = pt.st === "forming" ? "245,165,36" : !pt.ok ? "164,172,182" : pt.st === "up" ? "34,176,125" : "229,72,77";
      if (pt.poly && pt.lines.length === 2) {
        const [u, d] = pt.lines, q = [[u[0], u[1]], [u[2], u[3]], [d[2], d[3]], [d[0], d[1]]].map(([i, v]) => [X(i), Y(v)]);
        if (q.every(([x, y]) => x != null && y != null)) { ctx.fillStyle = `rgba(${col},.07)`; ctx.beginPath(); q.forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath(); ctx.fill(); }
      }
      ctx.strokeStyle = `rgba(${col},.85)`; ctx.lineWidth = 1.5; ctx.setLineDash([]); ctx.beginPath();
      let ok = true;
      pt.pts.forEach(([i, v], k) => { const x = X(i), y = Y(v); if (x == null || y == null) { ok = false; return; } k ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      if (ok && !pt.poly) ctx.stroke();
      ctx.font = `10px ${FONT}`;
      for (const [i0, v0, i1, v1, label] of pt.lines) {
        const x0 = X(i0), y0 = Y(v0), x1 = X(i1), y1 = Y(v1);
        if ([x0, y0, x1, y1].includes(null)) continue;
        ctx.strokeStyle = `rgba(${col},.9)`; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
        if (label && !small) { ctx.fillStyle = `rgba(${col},.95)`; ctx.textAlign = "left"; ctx.fillText(label, x0 + 3, y0 + (pt.dir < 0 ? 12 : -4)); }
      }
      const vs = pt.pts.map(([, v]) => v), yTop = Y(Math.max(...vs)), yBot = Y(Math.min(...vs)), bull = pt.dir > 0 || (pt.dir === 0 && pt.st === "up");
      const ly = bull ? (yBot ?? 0) + 16 : (yTop ?? 0) - 8, txt = `${pt.name} · ${pt.status}`;
      ctx.font = `600 10.5px ${FONT}`;
      const w = ctx.measureText(txt).width + 10, lx = Math.max(2, Math.min(size.width - w - 2, (xa + X(pt.i1)) / 2 - w / 2));
      if (yTop != null && yBot != null && !small && free(lx, ly - 11, w, 15)) {
        ctx.fillStyle = `rgba(${col},.18)`; ctx.fillRect(lx, ly - 11, w, 15);
        ctx.fillStyle = `rgb(${col})`; ctx.textAlign = "left"; ctx.fillText(txt, lx + 5, ly);
      }
      if (pt.target != null && (rank < 2 || !pt.reached) && !small) {
        const yt = Y(pt.target), x1 = X(pt.j + Math.max(8, Math.round((pt.i1 - pt.i0) / 2)));
        if (yt != null && x1 != null) {
          ctx.strokeStyle = `rgba(${col},.8)`; ctx.setLineDash([4, 3]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(xb, yt); ctx.lineTo(x1, yt); ctx.stroke(); ctx.setLineDash([]);
          ctx.font = `10px ${FONT}`; ctx.fillStyle = `rgb(${col})`; ctx.textAlign = "left";
          const t = `목표 ${this.px(pt.target)}${pt.reached ? " ✓ 도달" : ""}`;
          if (free(x1 + 3, yt - 8, ctx.measureText(t).width, 12)) ctx.fillText(t, x1 + 3, yt + 3);
        }
      }
    });
  }
  _drawProfiles(ctx, size, sessions) {
    const ts = this.chart.timeScale(), bw = ts.options().barSpacing;
    for (const s of sessions) {
      const xa = ts.logicalToCoordinate(s.i0), xb = ts.logicalToCoordinate(s.i1);
      if (xa == null || xb == null || xb < -50 || xa > size.width) continue;
      const x0 = xa - bw / 2, w = Math.max(4, (xb - xa + bw) * 0.9);
      for (const b of s.bins) {
        const y1 = this.candle.priceToCoordinate(b.hi), y2 = this.candle.priceToCoordinate(b.lo);
        if (y1 == null || y2 == null) continue;
        const h = Math.max(1, y2 - y1 - 1), wb = w * b.buy / s.max, wsl = w * b.sell / s.max, a = b.va ? 0.32 : 0.13;
        ctx.fillStyle = `rgba(242,54,69,${a})`; ctx.fillRect(x0, y1, wsl, h);
        ctx.fillStyle = `rgba(8,153,129,${a})`; ctx.fillRect(x0 + wsl, y1, wb, h);
      }
      const line = (price, color, dash, x1 = x0 + w) => {
        const y = this.candle.priceToCoordinate(price);
        if (y == null) return null;
        ctx.strokeStyle = color; ctx.setLineDash(dash); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke(); ctx.setLineDash([]);
        return y;
      };
      line(s.vah, "rgba(164,172,182,.45)", [3, 3]); line(s.val, "rgba(164,172,182,.45)", [3, 3]);
      const y = line(s.poc, "rgba(245,165,36,.95)", [], s.naked ? size.width : x0 + w);
      ctx.font = "10px " + FONT; ctx.fillStyle = "rgba(230,232,234,.6)";
      if (s.name && w > 40) ctx.fillText(s.name, x0 + 2, (this.candle.priceToCoordinate(s.bins.at(-1).hi) ?? 12) - 3);
      if (s.naked && y != null) { ctx.fillStyle = "rgba(245,165,36,.9)"; ctx.fillText("nPOC", Math.min(size.width - 34, x0 + w + 4), y - 3); }
    }
  }

  // 볼륨 프로파일: 화면에 보이는 봉만으로 계산해서 오른쪽에 가로 막대로
  _drawVP(ctx, size) {
    const it = this.ind.find((x) => x.profile && !x.spec.hidden);
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
      ctx.fillStyle = `rgba(8,153,129,${a})`; ctx.fillRect(right - wb - ws, y1, wb, h);
      ctx.fillStyle = `rgba(242,54,69,${a})`; ctx.fillRect(right - ws, y1, ws, h);
    }
    const py = this.candle.priceToCoordinate(vp.poc);
    if (py != null) { ctx.strokeStyle = "rgba(245,165,36,.85)"; ctx.setLineDash([4, 3]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(size.width, py); ctx.stroke(); ctx.setLineDash([]); }
  }

  // ------------------------------------------------------------ 흐름 오버레이 (flow.js — 코인만)
  get crypto() { return D.isCrypto(this.exchange); }
  async refreshFlow() {
    clearInterval(this._flowTimer); clearInterval(this._liqTimer);
    const o = this.opts.overlays || {}, want = this.crypto && (o.walls || o.whales || this.opts.wantFlow?.(this));
    if (!this.crypto) { this.flow.snap = this.flow.liq = null; this.flow.err = ""; this._flowRedraw(); return; }
    if (want) { await this._loadSnap(); this._flowTimer = setInterval(() => !document.hidden && this._loadSnap(), 15000); }
    if (o.liq && this.exchange !== "upbit") { await this._loadLiq(); this._liqTimer = setInterval(() => !document.hidden && this._loadLiq(), 60000); }
    else { this.flow.liq = null; this.liqLayer.update(); }
    this._flowRedraw();
  }
  async _loadSnap() {
    const ex = this.exchange, sym = this.symbol;
    try {
      const d = await D.flowSnapshot({ exchange: ex, symbol: sym });
      if (ex !== this.exchange || sym !== this.symbol) return;
      this.flow.snap = d; this.flow.err = "";
      const w = d.whaleTrades;   // 고래 체결은 모아 둔다 (한 번에 최근 상위 10건만 오므로)
      if (w) for (const x of w.top || []) this.flow.whales.set(`${x.t}:${x.price}:${x.qty}`, { ...x, minUsd: w.threshold });
      if (this.flow.whales.size > 300) this.flow.whales = new Map([...this.flow.whales].slice(-300));
    } catch (e) { if (ex === this.exchange && sym === this.symbol) this.flow.err = e.message || String(e); }
    this._flowRedraw();
  }
  async _loadLiq() {
    const ex = this.exchange, sym = this.symbol;
    try {
      const d = await D.liquidation({ symbol: sym });
      if (ex !== this.exchange || sym !== this.symbol) return;
      this.flow.liq = d;
    } catch (e) { if (ex === this.exchange && sym === this.symbol) { this.flow.liq = null; this.flow.liqErr = e.message || String(e); } }
    this._flowRedraw();
  }
  _flowRedraw() { this.wallLayer.update(); this.whaleLayer.update(); this.liqLayer.update(); this._legend(); this.opts.onFlow?.(this); }

  // 호가 벽: 가격대 띠 + 오른쪽에서 뻗는 막대
  _drawWalls(ctx, size) {
    const ob = this.opts.overlays?.walls && this.flow.snap?.orderBook;
    if (!ob) return;
    const walls = [...ob.bidWalls.map((w) => ({ ...w, side: "bid" })), ...ob.askWalls.map((w) => ({ ...w, side: "ask" }))];
    const maxN = Math.max(1, ...walls.map((w) => w.notional)), half = ob.mid * 0.0005, cur = ob.quote === "KRW" ? "₩" : "$";
    ctx.font = "10px " + FONT;
    const used = [];   // 글자끼리 겹치면 큰 벽 글자만
    walls.sort((a, b) => b.notional - a.notional);
    for (const w of walls) {
      const y1 = this.candle.priceToCoordinate(w.price + half), y2 = this.candle.priceToCoordinate(w.price - half);
      if (y1 == null || y2 == null) continue;
      const col = w.side === "bid" ? "8,153,129" : "242,54,69", k = w.notional / maxN, h = Math.max(3, y2 - y1), y = (y1 + y2) / 2;
      ctx.fillStyle = `rgba(${col},${(0.06 + 0.12 * k).toFixed(3)})`; ctx.fillRect(0, y - h / 2, size.width, h);
      const len = 30 + 110 * k;
      ctx.fillStyle = `rgba(${col},.55)`; ctx.fillRect(size.width - len, y - Math.max(2, h / 2), len, Math.max(4, h));
      if (used.some((u) => Math.abs(u - y) < 12)) continue;
      used.push(y);
      ctx.fillStyle = `rgba(${col},1)`; ctx.textAlign = "right";
      ctx.fillText(`${w.side === "bid" ? "매수벽" : "매도벽"} ${cur}${big(w.notional)} (${w.distPct >= 0 ? "+" : ""}${w.distPct.toFixed(2)}%)`, size.width - len - 4, y - 3);
    }
    ctx.textAlign = "left";
  }
  // 고래 체결 버블 (봉 시각 · 체결가)
  _drawWhales(ctx) {
    if (!this.opts.overlays?.whales || !this.flow.whales.size || !this.candles.length) return;
    const ts = this.chart.timeScale(), c = this.candles, step = D.IV_SEC[this.interval] || 3600, cur = this.flow.snap?.whaleTrades?.quote === "KRW" ? "₩" : "$";
    ctx.font = "10px " + FONT;
    for (const t of this.flow.whales.values()) {
      const sec = Math.floor(t.t / 1000);
      if (sec < c[0].time || sec > c.at(-1).time + step) continue;
      const bar = this._barTime(sec), x = bar != null ? ts.timeToCoordinate(bar) : null, y = this.candle.priceToCoordinate(t.price);
      if (x == null || y == null) continue;
      const r = Math.min(18, 4 + 4 * Math.sqrt(t.notional / (t.minUsd || t.notional)));
      const col = t.side === "buy" ? "8,153,129" : "242,54,69";
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${col},.25)`; ctx.fill();
      ctx.lineWidth = 1.2; ctx.strokeStyle = `rgba(${col},.95)`; ctx.stroke();
      if (r >= 9) { ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.fillText(cur + big(t.notional), x, y - r - 3); }
    }
    ctx.textAlign = "left";
  }
  // 청산 구간 (추정): 금액이 클수록 굵고 진한 주황 띠
  _drawLiq(ctx, size) {
    const d = this.opts.overlays?.liq && this.flow.liq;
    if (!d) return;
    const all = [...d.longClusters.map((x) => ({ ...x, side: "long" })), ...d.shortClusters.map((x) => ({ ...x, side: "short" }))].filter((x) => Number.isFinite(x.price));
    const mx = Math.max(1, ...all.map((x) => Number.isFinite(x.estUsd) ? x.estUsd : 0));
    ctx.font = "10px " + FONT;
    const used = [];
    for (const x of all.sort((a, b) => (b.estUsd || 0) - (a.estUsd || 0))) {
      const y = this.candle.priceToCoordinate(x.price);
      if (y == null) continue;
      const k = Number.isFinite(x.estUsd) ? x.estUsd / mx : 0.3, h = 2 + 8 * k;
      const g = ctx.createLinearGradient(0, 0, size.width, 0);
      g.addColorStop(0, `rgba(${COL.heat},0)`); g.addColorStop(0.35, `rgba(${COL.heat},${(0.15 + 0.45 * k).toFixed(3)})`); g.addColorStop(1, `rgba(${COL.heat},${(0.25 + 0.6 * k).toFixed(3)})`);
      ctx.fillStyle = g; ctx.fillRect(0, y - h / 2, size.width, h);
      if (used.some((u) => Math.abs(u - y) < 12)) continue;
      used.push(y);
      ctx.fillStyle = `rgba(255,183,77,${(0.6 + 0.4 * k).toFixed(2)})`; ctx.textAlign = "left";
      ctx.fillText(`추정 ${x.side === "long" ? "롱" : "숏"} 청산 ${x.mainLev}배${Number.isFinite(x.estUsd) ? ` ~$${big(x.estUsd)}` : ""}${x.wall ? " +벽" : ""}`, 6, y - h / 2 - 2);
    }
  }
  _barTime(t) {
    const c = this.candles;
    let lo = 0, hi = c.length - 1;
    if (!c.length || t < c[0].time) return null;
    while (lo < hi) { const m = (lo + hi + 1) >> 1; if (c[m].time <= t) lo = m; else hi = m - 1; }
    return c[lo].time;
  }

  // 보이는 캔들만으로 세로 범위 (멀리 있는 청산 추정선·호가벽 때문에 캔들이 눌리지 않게)
  _autoscale(original) {
    const r = this.chart?.timeScale().getVisibleLogicalRange(), c = this.candles;
    if (!r || !c?.length || this.ctype === "line" || this.ctype === "area") return original();
    let lo = Infinity, hi = -Infinity;
    for (let i = Math.max(0, Math.floor(r.from)); i <= Math.min(c.length - 1, Math.ceil(r.to)); i++) { lo = Math.min(lo, c[i].low); hi = Math.max(hi, c[i].high); }
    if (!Number.isFinite(lo)) return original();
    return { priceRange: { minValue: lo, maxValue: hi } };
  }

  // ------------------------------------------------------------ 차트 종류 · 가격축 · 화면 · 스크린샷
  setChartType(t) { this.ctype = t; this._display(); }
  _display() {
    const t = this.ctype || "candles", c = this.candles, up = COL.up, dn = COL.down, clear = "rgba(0,0,0,0)", L = LC();
    const own = ["candles", "hollow", "ha"].includes(t);
    if (t === "hollow") this.candle.applyOptions({ upColor: clear, downColor: dn, borderVisible: true, borderUpColor: up, borderDownColor: dn, wickUpColor: up, wickDownColor: dn, lastValueVisible: true, priceLineVisible: true });
    else if (own) this.candle.applyOptions({ upColor: up, downColor: dn, borderVisible: false, wickUpColor: up, wickDownColor: dn, lastValueVisible: true, priceLineVisible: true });
    else this.candle.applyOptions({ upColor: clear, downColor: clear, borderVisible: false, wickUpColor: clear, wickDownColor: clear, lastValueVisible: false, priceLineVisible: false });
    this.candle.setData(t === "ha" ? heikinAshi(c) : c);
    if (this.dispType !== t) {
      if (this.disp) { try { this.chart.removeSeries(this.disp); } catch (e) { /* 무시 */ } this.disp = null; }
      this.dispType = t;
      const pf = { type: "price", precision: this.prec, minMove: 10 ** -this.prec };
      if (t === "bars") this.disp = this.chart.addSeries(L.BarSeries, { upColor: up, downColor: dn, thinBars: false, priceFormat: pf }, 0);
      else if (t === "line") this.disp = this.chart.addSeries(L.LineSeries, { color: COL.accent, lineWidth: 2, priceFormat: pf }, 0);
      else if (t === "area") this.disp = this.chart.addSeries(L.AreaSeries, { lineColor: COL.accent, topColor: "rgba(41,98,255,.35)", bottomColor: "rgba(41,98,255,0)", lineWidth: 2, priceFormat: pf }, 0);
    }
    if (this.disp) this.disp.setData(t === "bars" ? c : c.map((b) => ({ time: b.time, value: b.close })));
  }
  // 로그 눈금은 가격 창에만 (아래 창 지표는 항상 보통 눈금)
  setLog(on) { this.log = !!on; this._scaleModes(); }
  _scaleModes() {
    this.chart.panes().forEach((pn, i) => { try { pn.priceScale("right").applyOptions({ mode: i === 0 && this.log ? 1 : 0 }); } catch (e) { /* 무시 */ } });
  }
  showBars(n) {
    const len = this.candles.length;
    if (!len) return;
    this.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, len - n), to: len + 6 });
  }
  screenshot() {
    const cv = this.chart.takeScreenshot(), ctx = cv.getContext("2d"), b = this.candles.at(-1);
    ctx.font = "bold 14px " + FONT; ctx.fillStyle = "#d1d4dc";
    ctx.fillText(`${this.symbol} · ${D.EX_SHORT[this.exchange]} · ${D.IV_LABEL[this.interval]} · ${b ? this.px(b.close) : ""} · ${new Date().toLocaleString("ko-KR")}`, 10, cv.height - 12);
    return cv;
  }

  // ------------------------------------------------------------ 범례 (OHLCV · 지표 값 · 흐름 설명)
  _legend(p) {
    const c = this.candles, name = this.meta.name || D.nameOf(this.exchange, this.symbol);
    const head = `<b>${esc(this.symbol || "")}</b>${name ? ` <span class="dim">${esc(name)}</span>` : ""} <span class="muted">· ${D.IV_LABEL[this.interval] || ""} · ${D.EX_SHORT[this.exchange] || ""}</span>`;
    if (!c.length) { this.legendEl.innerHTML = `<div class="lg-main" style="top:4px">${head}</div>`; return; }
    let idx = c.length - 1;
    if (p?.time != null) { const k = this._idxOf(p.time); if (k >= 0) idx = k; }
    const b = c[idx], prev = c[idx - 1] || b, chg = (b.close / prev.close - 1) * 100, cls = b.close >= b.open ? "up" : "down";
    let heights = [];
    try { heights = this.chart.panes().map((pn) => pn.getHeight()); } catch (e) { heights = [0]; }
    const tops = heights.map((_, i) => heights.slice(0, i).reduce((s, h) => s + h + 1, 0));
    const val = (v) => v == null ? "–" : this.px(v);
    const nMain = this.ind.filter((x) => x.pane === 0).length;
    let html = `<div class="lg-main" style="top:${(tops[0] || 0) + 4}px"><div class="lg-head">${head}${nMain ? `<span class="lg-more">지표 ${nMain} ▾</span>` : ""}</div>
      <div class="lg-ohlc"><span class="muted">시</span><span class="${cls}">${this.px(b.open)}</span> <span class="muted">고</span><span class="${cls}">${this.px(b.high)}</span> <span class="muted">저</span><span class="${cls}">${this.px(b.low)}</span> <span class="muted">종</span><span class="${cls}">${this.px(b.close)}</span>
      <span class="${chg >= 0 ? "up" : "down"}">${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%</span> <span class="muted">거래량</span> ${big(b.volume || 0)}</div>`;
    const vals = (it) => it.last.plots.filter((pl) => !SKIP.includes(pl.type) && pl.legend !== false).map((pl) => `<span style="color:${pl.color || it.spec.color || "inherit"}">${pl.type === "hist" && it.pane === 0 ? big(pl.data[idx] ?? 0) : val(pl.data[idx])}</span>`).join(" ");
    const acts = (it) => `<span class="lg-act"><button data-lg="hide" data-id="${it.spec.id}" title="${it.spec.hidden ? "보이기" : "숨기기"}">${it.spec.hidden ? "◌" : "◉"}</button><button data-lg="set" data-id="${it.spec.id}" title="설정">⚙</button><button data-lg="del" data-id="${it.spec.id}" title="지우기">✕</button></span>`;
    const pstr = (it) => { const v = Object.entries(it.params).filter(([k]) => k !== "expr" && k !== "overlay" && k !== "name").map(([, x]) => x); return v.length ? ` <span class="muted">${esc(v.join(","))}</span>` : ""; };
    const extra = (it) => it.profile && this.vp ? ` <span class="muted">POC</span> ${this.px(this.vp.poc)} <span class="muted">가치영역</span> ${this.px(this.vp.val)}~${this.px(this.vp.vah)}` : it.last.note ? ` <span class="muted">${esc(it.last.note)}</span>` : "";
    for (const it of this.ind.filter((x) => x.pane === 0)) {
      html += `<div class="lg-row ${it.spec.hidden ? "off" : ""}"><span style="color:${it.spec.color || it.last.plots.find((pl) => pl.color)?.color || "inherit"}">${esc(labelOf(it.spec))}${pstr(it)}</span> ${it.spec.hidden ? "" : vals(it) + extra(it)}${acts(it)}</div>`;
    }
    const o = this.opts.overlays || {}, f = this.flow, notes = [];
    if (this.crypto) {
      if (o.walls && f.snap?.orderBook) notes.push(`호가벽 ${f.snap.orderBook.bidWalls.length + f.snap.orderBook.askWalls.length}개 (0.1% 묶음)`);
      if (o.whales) notes.push(`고래 체결 ≥ $${big(f.snap?.whaleTrades?.minUsd || 500000)} · ${f.whales.size}건 (열어 둔 동안 모음)`);
      if (o.liq) notes.push(f.liq ? `청산 구간 = <b class="heat">추정</b>(OI 증가 구간 × 가정 레버리지, 실제 청산 데이터 아님)` : this.exchange === "upbit" ? "청산 추정은 바이낸스 선물(USDT)만" : "청산 추정 불러오는 중…");
      if (f.err && (o.walls || o.whales)) notes.push(`<span class="down">흐름: ${esc(f.err)}</span>`);
    } else if (o.walls || o.whales || o.liq) notes.push("흐름 오버레이(호가·고래·청산)는 코인만 지원");
    if (this.full) notes.push(`전체 과거 ${c.length.toLocaleString()}봉`);
    if (notes.length) html += `<div class="lg-note">${notes.join(" · ")}</div>`;
    html += `</div>`;
    for (const it of this.ind.filter((x) => x.pane > 0)) {
      const top = tops[it.pane];
      if (top == null) continue;
      html += `<div class="lg-row lg-sub ${it.spec.hidden ? "off" : ""}" style="top:${top + 3}px"><span class="dim">${esc(labelOf(it.spec))}${pstr(it)}</span>${acts(it)} ${it.last.plots.filter((pl) => !SKIP.includes(pl.type) && pl.legend !== false).map((pl) => `<span style="color:${pl.color || it.spec.color || "inherit"}">${smart(pl.data[idx])}</span>`).join(" ")}${it.last.note ? ` <span class="accent">${esc(it.last.note)}</span>` : ""}</div>`;
    }
    this.legendEl.innerHTML = html;
  }
  _idxOf(t) {
    const c = this.candles;
    let lo = 0, hi = c.length - 1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (c[m].time === t) return m; if (c[m].time < t) lo = m + 1; else hi = m - 1; }
    return -1;
  }
}

// 하이킨 아시 캔들 (차트 표시용 — 지표 계산은 실제 캔들로)
function heikinAshi(c) {
  const out = [];
  c.forEach((b, i) => {
    const close = (b.open + b.high + b.low + b.close) / 4;
    const open = i ? (out[i - 1].open + out[i - 1].close) / 2 : (b.open + b.close) / 2;
    out.push({ time: b.time, open, high: Math.max(b.high, open, close), low: Math.min(b.low, open, close), close });
  });
  return out;
}

function toData(c, pl) {
  return c.map((b, i) => {
    const v = pl.data[i];
    if (v == null || Number.isNaN(v)) return { time: b.time };
    const d = { time: b.time, value: v };
    if (pl.colors?.[i]) d.color = pl.colors[i];
    return d;
  });
}

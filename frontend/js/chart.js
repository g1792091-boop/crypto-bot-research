// 자체 차트 엔진 (lightweight-charts v5 + 자체 보조지표 + 오버레이)
import { INDICATORS, volumeProfile } from "./ind.js";
import { IV_LABEL, api, big, css, esc, fmt, px } from "./core.js";

const LC = LightweightCharts;

// 캔버스에 직접 그리는 레이어 (청산맵 · 고래 · 호가벽 · 추세선). 차트와 함께 확대/이동된다.
export class Layer {
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
    this.opts = { overlays: { heat: false, whales: false, bots: true, scenario: true, sbot: true }, ...opts };
    this.symbol = opts.symbol; this.interval = opts.interval;
    this.indicators = opts.indicators || [];
    this.candles = [];
    this.ind = [];            // {spec, series:[], pane}
    this.ext = {};            // 서버 파생 데이터
    this.heat = null; this.whales = null; this.markers = null; this.scenario = null;
    this.priceLines = []; this.userLines = []; this.trends = [];
    this.drawMode = null; this.pending = null;

    el.innerHTML = `<div class="tc-chart"></div><div class="tc-legend"></div><div class="tc-ladder" hidden><canvas></canvas><div class="tc-ltip" hidden></div></div>`;
    this.legendEl = el.querySelector(".tc-legend");
    this.legendEl.addEventListener("click", (e) => {      // 범례의 지표 숨기기 · 설정 · 지우기 (트레이딩뷰 방식)
      const b = e.target.closest("[data-lg]");
      if (b) { e.stopPropagation(); this.opts.onLegend?.(b.dataset.lg, +b.dataset.ii, b); }
    });
    this.ladderEl = el.querySelector(".tc-ladder");
    this.chart = LC.createChart(el.querySelector(".tc-chart"), {
      autoSize: true,
      layout: { background: { type: "solid", color: css("--chart-bg") || css("--panel") }, textColor: css("--text-2"), fontSize: 11, attributionLogo: false,
        fontFamily: getComputedStyle(document.body).fontFamily, panes: { separatorColor: css("--line"), separatorHoverColor: "rgba(41,98,255,.35)" } },
      grid: { vertLines: { color: "rgba(42,46,57,.55)" }, horzLines: { color: "rgba(42,46,57,.55)" } },
      rightPriceScale: { borderColor: css("--line"), scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: css("--line"), timeVisible: true, secondsVisible: false, rightOffset: 10 },
      crosshair: { mode: LC.CrosshairMode.Normal,
        vertLine: { color: "#787b86", width: 1, style: 3, labelBackgroundColor: "#363a45" },
        horzLine: { color: "#787b86", width: 1, style: 3, labelBackgroundColor: "#363a45" } },
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
    this.boxLayer = new Layer((ctx, size) => this._drawBoxes(ctx, size), "bottom");
    this.fcLayer = new Layer((ctx, size) => this._drawForecast(ctx, size), "bottom");
    this.fc = null; this.fcSeries = [];
    this.fpLayer = new Layer((ctx, size) => this._drawFootprint(ctx, size), "top");
    this.fp = null; this.fpMarkers = [];
    this.countdown = new Countdown(this);
    // 가격 사다리: 차트가 다시 그려질 때마다(확대·이동·가격축 드래그) 옆 사다리도 같은 높이로 맞춘다
    this.ladderHook = new Layer((ctx, size) => { this._paneH = size.height; this._paneW = size.width; this._scheduleLadder(); }, "bottom");
    this.candle.attachPrimitive(this.ladderHook);
    this.book = null;
    this._setupLadder();
    [this.vpLayer, this.boxLayer, this.fcLayer, this.srLayer, this.heatLayer, this.whaleLayer, this.drawLayer, this.fpLayer, this.countdown].forEach((l) => this.candle.attachPrimitive(l));
    this.sigMarkers = [];     // 보조지표 신호 (골든크로스·UT Bot·다이버전스 등) — 가격 창 화살표
    this._cdTimer = setInterval(() => !document.hidden && this.countdown.update(), 1000);
    this.editLines = {};
    this._setupDrag();
    this.chart.subscribeCrosshairMove((p) => { this._legend(p); this._crossY = p.point?.y ?? null; if (!this.ladderEl.hidden) this._scheduleLadder(); });
    this.chart.subscribeClick((p) => this._click(p));
  }

  destroy() { this._ro?.disconnect(); clearInterval(this._timer); clearInterval(this._cdTimer); clearInterval(this._bookTimer); this.chart.remove(); this.el.innerHTML = ""; }

  // 지금 보고 있는 코인·봉인지 확인 (늦게 도착한 이전 코인의 응답을 버리기 위함)
  _is(sym, iv) { return sym === this.symbol && iv === this.interval; }

  async load(symbol = this.symbol, interval = this.interval) {
    const changed = symbol !== this.symbol || interval !== this.interval || !this.candles.length;
    this.symbol = symbol; this.interval = interval;
    if (changed) {
      // 이전 코인의 포지션선·시나리오·청산맵·고래·지지저항이 새 코인 차트에 남지 않도록 즉시 비운다
      clearInterval(this._timer);
      this.markers = this.heat = this.whales = this.sr = this.scenario = this.ai = this.sbot = null;
      this.ext = {}; this.sigMarkers = [];
      this.setForecast(null); this.fp = null; this.fpMarkers = []; this.fpLayer.update();
      this.book = null; if (this.opts.overlays.ladder) this._loadBook();
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
    this._display();
    if (changed) { this.chart.timeScale().fitContent(); this.chart.timeScale().scrollToRealTime(); this.opts.onLoad?.(this); }
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
      if (!this.ctype || this.ctype === "candles" || this.ctype === "hollow") this.candle.update(b);
    }
    if (this.ctype && this.ctype !== "candles" && this.ctype !== "hollow") this._display();
    this._tickN = (this._tickN || 0) + 1;
    if (newBar || this._tickN % 5 === 0) this.renderIndicators(true);
    if (newBar) this.refreshOverlays();
    else if (this.opts.overlays.footprint && this._tickN % 10 === 0) this.loadFootprint();
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
    if (need.has("btc")) jobs.push(api(`/api/candles?symbol=BTCUSDT&interval=${iv}&limit=${Math.max(500, this.candles.length || 1000)}`).then((d) => (ext.btc = d.candles)).catch(() => {}));
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
      this._applySignals(); this.boxLayer.update();
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
        if (["signals", "boxes", "profiles", "patterns"].includes(pl.type)) return null;   // 화살표·상자는 따로 그림
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
        if (spec.hidden) s.applyOptions({ visible: false });
        return s;
      });
      if (def.pane === "volume") this.chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      const first = series.find(Boolean);
      if (r.levels && first) r.levels.forEach((lv) => first.createPriceLine({ price: lv, color: "rgba(164,172,182,.35)", lineWidth: 1, lineStyle: 2, axisLabelVisible: false }));
      this.ind.push({ spec, params, series, pane, last: r, profile: !!def.profile });
    }
    this._applySignals();
    this.vpLayer.update(); this.boxLayer.update();
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

  // FVG · 오더블록 같은 가격 구간 상자
  _drawBoxes(ctx, size) {
    const c = this.candles, ts = this.chart.timeScale();
    if (!c.length) return;
    ctx.font = "10px " + getComputedStyle(document.body).fontFamily;
    for (const it of this.ind) {
      if (it.pane !== 0) continue;
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

  // 차트 패턴: 스윙 점을 잇는 선 + 경계선/넥라인 + 이름·상태 + 목표가(측정 이동)
  _drawPatterns(ctx, size, pats) {
    const ts = this.chart.timeScale(), s = this.candle, X = (i) => ts.logicalToCoordinate(i), Y = (v) => s.priceToCoordinate(v);
    const font = getComputedStyle(document.body).fontFamily, used = [];
    // 글자끼리 겹치면 건너뛴다 (최근 패턴 우선)
    const free = (x, y, w, h) => { if (used.some((r) => x < r.x + r.w && x + w > r.x && y < r.y + r.h && y + h > r.y)) return false; used.push({ x, y, w, h }); return true; };
    [...pats].reverse().forEach((pt, rank) => {
      const xa = X(pt.i0), xb = X(pt.j);
      if (xa == null || xb == null || xb < -80 || xa > size.width + 80) return;
      const small = xb - xa < 36;   // 너무 작게 보이면 선만
      const col = pt.st === "forming" ? "245,165,36" : !pt.ok ? "164,172,182" : pt.st === "up" ? "34,176,125" : "229,72,77";
      // 삼각형·깃발·채널: 두 경계선 사이를 옅게 칠함
      if (pt.poly && pt.lines.length === 2) {
        const [u, d] = pt.lines, q = [[u[0], u[1]], [u[2], u[3]], [d[2], d[3]], [d[0], d[1]]].map(([i, v]) => [X(i), Y(v)]);
        if (q.every(([x, y]) => x != null && y != null)) { ctx.fillStyle = `rgba(${col},.07)`; ctx.beginPath(); q.forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath(); ctx.fill(); }
      }
      // 스윙 점 연결선
      ctx.strokeStyle = `rgba(${col},.85)`; ctx.lineWidth = 1.5; ctx.setLineDash([]); ctx.beginPath();
      let ok = true;
      pt.pts.forEach(([i, v], k) => { const x = X(i), y = Y(v); if (x == null || y == null) { ok = false; return; } k ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      if (ok && !pt.poly) ctx.stroke();
      // 경계선 · 넥라인 (마지막 점 이후 부분은 점선)
      ctx.font = `10px ${font}`;
      for (const [i0, v0, i1, v1, label] of pt.lines) {
        const x0 = X(i0), y0 = Y(v0), x1 = X(i1), y1 = Y(v1);
        if ([x0, y0, x1, y1].includes(null)) continue;
        ctx.strokeStyle = `rgba(${col},.9)`; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
        if (label && !small) { ctx.fillStyle = `rgba(${col},.95)`; ctx.textAlign = "left"; ctx.fillText(label, x0 + 3, y0 + (pt.dir < 0 ? 12 : -4)); }
      }
      // 이름 · 상태
      const vs = pt.pts.map(([, v]) => v), yTop = Y(Math.max(...vs)), yBot = Y(Math.min(...vs)), bull = pt.dir > 0 || (pt.dir === 0 && pt.st === "up");
      const ly = bull ? (yBot ?? 0) + 16 : (yTop ?? 0) - 8, txt = `${pt.name} · ${pt.status}`;
      ctx.font = `600 10.5px ${font}`;
      const w = ctx.measureText(txt).width + 10, lx = Math.max(2, Math.min(size.width - w - 2, (xa + X(pt.i1)) / 2 - w / 2));
      if (yTop != null && yBot != null && !small && free(lx, ly - 11, w, 15)) {
        ctx.fillStyle = `rgba(${col},.18)`; ctx.fillRect(lx, ly - 11, w, 15);
        ctx.fillStyle = `rgb(${col})`; ctx.textAlign = "left"; ctx.fillText(txt, lx + 5, ly);
      }
      // 목표가 (지난 패턴 중 이미 도달한 것은 최근 2개만)
      if (pt.target != null && (rank < 2 || !pt.reached) && !small) {
        const yt = Y(pt.target), x1 = X(pt.j + Math.max(8, Math.round((pt.i1 - pt.i0) / 2)));
        if (yt != null && x1 != null) {
          ctx.strokeStyle = `rgba(${col},.8)`; ctx.setLineDash([4, 3]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(xb, yt); ctx.lineTo(x1, yt); ctx.stroke(); ctx.setLineDash([]);
          ctx.font = `10px ${font}`; ctx.fillStyle = `rgb(${col})`; ctx.textAlign = "left";
          const t = `목표 ${px(pt.target)}${pt.reached ? " ✓ 도달" : ""}`;
          if (free(x1 + 3, yt - 8, ctx.measureText(t).width, 12)) ctx.fillText(t, x1 + 3, yt + 3);
        }
      }
    });
  }

  // 세션 볼륨 프로파일: 세션 왼쪽 끝에서 오른쪽으로 자라는 막대 + POC · 가치영역 · nPOC
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
        ctx.fillStyle = `rgba(229,72,77,${a})`; ctx.fillRect(x0, y1, wsl, h);
        ctx.fillStyle = `rgba(34,176,125,${a})`; ctx.fillRect(x0 + wsl, y1, wb, h);
      }
      const line = (price, color, dash, x1 = x0 + w) => {
        const y = this.candle.priceToCoordinate(price);
        if (y == null) return null;
        ctx.strokeStyle = color; ctx.setLineDash(dash); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke(); ctx.setLineDash([]);
        return y;
      };
      line(s.vah, "rgba(164,172,182,.45)", [3, 3]); line(s.val, "rgba(164,172,182,.45)", [3, 3]);
      const y = line(s.poc, "rgba(245,165,36,.95)", [], s.naked ? size.width : x0 + w);
      ctx.font = "10px " + getComputedStyle(document.body).fontFamily; ctx.fillStyle = "rgba(230,232,234,.6)";
      if (s.name && w > 40) ctx.fillText(s.name, x0 + 2, (this.candle.priceToCoordinate(s.bins.at(-1).hi) ?? 12) - 3);
      if (s.naked && y != null) { ctx.fillStyle = "rgba(245,165,36,.9)"; ctx.fillText("nPOC", Math.min(size.width - 34, x0 + w + 4), y - 3); }
    }
  }

  // ------------------------------------------------------------ 패턴 예측 (미래 구간 부채꼴 + 다음 봉 유령 캔들)
  setForecast(f) {
    const ts = this.chart.timeScale(), atEdge = this.candles.length && (ts.getVisibleLogicalRange()?.to ?? 0) >= this.candles.length - 3;
    this.fcSeries.forEach((s) => this.chart.removeSeries(s));
    this.fcSeries = [];
    this.fc = f && f.symbol === this.symbol && f.interval === this.interval && this.candles.length ? f : null;
    const a = this.fc?.analog, last = this.candles.at(-1);
    if (a?.times?.length) {
      const mk = (vals, color, style, width = 1) => {
        const s = this.chart.addSeries(LC.LineSeries, { color, lineWidth: width, lineStyle: style, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        s.setData([{ time: last.time, value: last.close }, ...a.times.map((t, h) => ({ time: t, value: vals[h] }))]);
        this.fcSeries.push(s);
      };
      mk(a.bands.p50, css("--accent"), 0, 2);
    }
    const nb = this.fc?.next_bar;
    if (nb?.candle) {
      const up = nb.candle.close >= nb.candle.open;
      const g = this.chart.addSeries(LC.CandlestickSeries, { upColor: "rgba(34,176,125,.25)", downColor: "rgba(229,72,77,.25)", borderVisible: true,
        borderUpColor: css("--up"), borderDownColor: css("--down"), wickUpColor: css("--up"), wickDownColor: css("--down"), priceLineVisible: false, lastValueVisible: false });
      g.setData([{ time: nb.time, ...nb.candle }]);
      LC.createSeriesMarkers(g, [{ time: nb.time, position: up ? "aboveBar" : "belowBar", shape: "circle", size: 0.4, color: css("--text-2"), text: nb.p_up === 50 ? "다음 봉 방향 불분명" : `다음 봉 ${nb.p_up > 50 ? "상승" : "하락"} ${Math.max(nb.p_up, 100 - nb.p_up)}%` }]);
      this.fcSeries.push(g);
    }
    // 최신 봉을 보고 있었다면 예측 구간(미래)이 잘 보이게: 코인·봉마다 처음 한 번은 최근 150봉 + 예측 구간으로 확대
    if (atEdge && this.fcSeries.length) {
      const key = `${this.symbol}:${this.interval}`, n = this.candles.length, hz = a?.times?.length || 1;
      if (this._fcZoom !== key) { this._fcZoom = key; ts.setVisibleLogicalRange({ from: Math.max(0, n - 150), to: n + hz + 4 }); }
      else ts.scrollToRealTime();
    }
    this.fcLayer.update();
  }

  _drawForecast(ctx) {
    const a = this.fc?.analog, last = this.candles.at(-1);
    if (!a?.times?.length || !last) return;
    const ts = this.chart.timeScale(), x0 = ts.timeToCoordinate(last.time), y0 = this.candle.priceToCoordinate(last.close);
    if (x0 == null || y0 == null) return;
    const pts = (key) => a.times.map((t, h) => [ts.timeToCoordinate(t), this.candle.priceToCoordinate(a.bands[key][h])]).filter(([x, y]) => x != null && y != null);
    const band = (lo, hi, fill) => {
      const L = pts(lo), H = pts(hi);
      if (!L.length || L.length !== H.length) return;
      ctx.beginPath(); ctx.moveTo(x0, y0);
      H.forEach(([x, y]) => ctx.lineTo(x, y));
      [...L].reverse().forEach(([x, y]) => ctx.lineTo(x, y));
      ctx.closePath(); ctx.fillStyle = fill; ctx.fill();
    };
    band("p10", "p90", "rgba(245,165,36,.08)");
    band("p25", "p75", "rgba(245,165,36,.16)");
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

  // ------------------------------------------------------------ 가격 사다리 (차트 옆 가격대 전부)
  // 가격축과 같은 높이에 칸마다: 가격 · 보이는 구간 거래량(매수/매도) · 호가 잔량 · 표시(지지·저항·POC·내 포지션·호가벽 …)
  _setupLadder() {
    const cv = this.ladderEl.querySelector("canvas"), tipEl = this.ladderEl.querySelector(".tc-ltip");
    cv.onmousemove = (e) => {
      const r = cv.getBoundingClientRect(), y = e.clientY - r.top, row = this._ladRows?.find((x) => y >= x.y1 && y < x.y2);
      if (!row) { tipEl.hidden = true; return; }
      const last = this.candles.at(-1)?.close, d = last ? (row.price / last - 1) * 100 : 0;
      tipEl.innerHTML = `<b>${px(row.price)}</b> <span class="muted">(현재가 대비 ${d >= 0 ? "+" : ""}${d.toFixed(2)}%)</span><br>`
        + `거래량 ${big(row.vol)} <span class="up">매수 ${big(row.buy)}</span> · <span class="down">매도 ${big(row.vol - row.buy)}</span><br>`
        + (row.bid || row.ask ? `호가 ${row.bid ? `<span class="up">매수 잔량 ${fmt(row.bid, 3)} ($${big(row.bidUsd)})</span>` : ""}${row.ask ? `<span class="down">매도 잔량 ${fmt(row.ask, 3)} ($${big(row.askUsd)})</span>` : ""}<br>` : "")
        + (row.tags.length ? row.tags.map((t) => `<span style="color:${t.color}">■</span> ${esc(t.full)}`).join("<br>") : "");
      tipEl.hidden = false;
      tipEl.style.top = `${Math.max(0, Math.min(this.ladderEl.clientHeight - tipEl.offsetHeight - 4, y + 12))}px`;
    };
    cv.onmouseleave = () => (tipEl.hidden = true);
    // 사다리 위에서 휠 = 차트 가격 확대/축소 대신 시간축 확대 (차트와 같은 동작)
    cv.onwheel = (e) => { e.preventDefault(); const ts = this.chart.timeScale(), r = ts.getVisibleLogicalRange(); if (!r) return;
      const k = e.deltaY > 0 ? 1.1 : 0.9, w = (r.to - r.from) * k; ts.setVisibleLogicalRange({ from: r.to - w, to: r.to }); };
  }

  setLadder(on) {
    this.opts.overlays.ladder = on;
    this.ladderEl.hidden = !on;
    this.el.classList.toggle("with-ladder", on);
    // 칸이 좁으면(분할 화면) 사다리를 좁게
    if (!this._ro) { this._ro = new ResizeObserver(() => { const w = this.el.clientWidth;
      this.el.classList.toggle("ladder-compact", w < 760); this.el.classList.toggle("ladder-tiny", w < 520); this._scheduleLadder(); }); this._ro.observe(this.el); }
    clearInterval(this._bookTimer);
    if (on) { this._loadBook(); this._bookTimer = setInterval(() => !document.hidden && this._loadBook(), 3000); }
    this._scheduleLadder();
  }

  async _loadBook() {
    const sym = this.symbol;
    try {
      const b = await api(`/api/orderbook?symbol=${sym}&rows=100`);
      if (sym !== this.symbol) return;
      this.book = b; this._scheduleLadder();
    } catch { /* 호가 없으면 거래량·레벨만 */ }
  }

  _scheduleLadder() {
    if (this._ladRaf || this.ladderEl.hidden) return;
    this._ladRaf = requestAnimationFrame(() => { this._ladRaf = 0; this._drawLadder(); });
  }

  // 사다리에 표시할 주요 가격
  _ladderTags(vis, rowsVP) {
    const tags = [], add = (price, short, full, color) => price && isFinite(price) && tags.push({ price, short, full, color });
    const up = css("--up"), down = css("--down"), acc = css("--accent"), info = css("--info");
    const last = this.candles.at(-1);
    if (rowsVP) { add(rowsVP.poc, "POC", "화면 구간 최다 거래 가격 (POC)", acc); add(rowsVP.vah, "VAH", "가치 영역 상단 (거래 70% 구간 위)", "#c98500"); add(rowsVP.val, "VAL", "가치 영역 하단", "#c98500"); }
    for (const z of this.sr?.zones || []) add(z.price, z.side === "resistance" ? "저항" : "지지", `${z.side === "resistance" ? "저항" : "지지"} 구간 · ${z.touches}회 닿음`, z.side === "resistance" ? down : up);
    const my = this._pos();
    if (my) { add(my.entry_price, "진입", `내 ${my.side === "long" ? "롱" : "숏"} 진입가`, info); add(my.stop, "손절", "내 손절가", down); add(my.take, "익절", "내 익절가", up); add(my.liq_price, "청산", "내 강제청산가", down); }
    const sc = this.opts.overlays.scenario && this.scenario;
    if (sc) { add(sc.entry, "계획진입", `시나리오 진입 (${sc.title})`, acc); add(sc.stop, "계획손절", "시나리오 손절", down); sc.targets?.forEach((t, i) => add(t, `목표${i + 1}`, `시나리오 목표 ${i + 1}`, up)); }
    this.userLines.forEach((u) => add(u, "선", "내가 그린 수평선", "#a4acb6"));
    // 전일 · 전주 고가/저가 (일봉보다 짧은 봉일 때)
    const sec = { "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800, "12h": 43200 }[this.interval];
    if (sec && last) {
      const day = Math.floor(last.time / 86400) * 86400, prev = this.candles.filter((b) => b.time >= day - 86400 && b.time < day);
      if (prev.length) { add(Math.max(...prev.map((b) => b.high)), "전일고", "전일 고가", "#d55181"); add(Math.min(...prev.map((b) => b.low)), "전일저", "전일 저가", "#d55181"); }
      const wk = Math.floor((last.time - 345600) / 604800) * 604800 + 345600, pw = this.candles.filter((b) => b.time >= wk - 604800 && b.time < wk);
      if (pw.length && sec <= 14400) { add(Math.max(...pw.map((b) => b.high)), "전주고", "전주 고가", "#3987e5"); add(Math.min(...pw.map((b) => b.low)), "전주저", "전주 저가", "#3987e5"); }
    }
    if (vis.length) { add(Math.max(...vis.map((b) => b.high)), "화면고", "화면 구간 최고가", "#8a919c"); add(Math.min(...vis.map((b) => b.low)), "화면저", "화면 구간 최저가", "#8a919c"); }
    // 호가벽: 잔량이 중앙값의 4배 이상
    const bk = this.book?.symbol === this.symbol ? this.book : null;
    if (bk) {
      const all = [...bk.bids, ...bk.asks].map((x) => x.qty).sort((a, b) => a - b), med = all[all.length >> 1] || 0;
      bk.bids.filter((x) => x.qty > med * 4).forEach((x) => add(x.price, "매수벽", `매수 호가벽 ${fmt(x.qty, 3)} ($${big(x.usd)})`, up));
      bk.asks.filter((x) => x.qty > med * 4).forEach((x) => add(x.price, "매도벽", `매도 호가벽 ${fmt(x.qty, 3)} ($${big(x.usd)})`, down));
    }
    return tags;
  }

  _drawLadder() {
    const box = this.ladderEl, cv = box.querySelector("canvas");
    if (!box.offsetParent) return;   // 칸이 너무 좁아 숨겨진 상태
    const W = box.clientWidth, Hb = box.clientHeight, H = Math.min(this._paneH || Hb, Hb), dpr = window.devicePixelRatio || 1;
    if (!W || !Hb) return;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(Hb * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(Hb * dpr); cv.style.width = W + "px"; cv.style.height = Hb + "px"; }
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, Hb);
    this._ladRows = [];
    const s = this.candle, top = s.coordinateToPrice(0), bot = s.coordinateToPrice(H), last = this.candles.at(-1);
    if (top == null || bot == null || !last || !(top > bot)) return;
    // 칸 간격: 한 칸이 16px 이상 되도록 1·2·2.5·5 ×10ⁿ 중 고른다
    const raw = (top - bot) * 16 / H, e10 = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * e10).find((v) => v >= raw);
    const dec = Math.max(0, -Math.floor(Math.log10(step)) + (step / 10 ** Math.floor(Math.log10(step)) === 2.5 ? 1 : 0));
    const key = (p) => Math.round(p / step);
    // 보이는 봉의 가격대별 거래량
    const r = this.chart.timeScale().getVisibleLogicalRange();
    const vis = r ? this.candles.slice(Math.max(0, Math.floor(r.from)), Math.min(this.candles.length, Math.ceil(r.to) + 1)) : [];
    const vol = new Map();
    for (const b of vis) {
      const a = key(b.low), z = key(b.high), n = z - a + 1, buy = b.taker_buy ?? b.volume / 2;
      if (n > 4000) continue;
      for (let k = a; k <= z; k++) { const v = vol.get(k) || { v: 0, b: 0 }; v.v += b.volume / n; v.b += buy / n; vol.set(k, v); }
    }
    // POC · 가치 영역 (이 칸 간격 기준)
    let vp = null;
    if (vol.size) {
      const ks = [...vol.keys()].sort((a, b) => a - b), tot = ks.map((k) => vol.get(k).v), all = tot.reduce((p, q) => p + q, 0);
      let pi = tot.indexOf(Math.max(...tot)), a = pi, z = pi, accv = tot[pi];
      while (accv < all * 0.7 && (a > 0 || z < ks.length - 1)) { const u = z < ks.length - 1 ? tot[z + 1] : -1, d = a > 0 ? tot[a - 1] : -1; if (u >= d) accv += tot[++z]; else accv += tot[--a]; }
      vp = { poc: ks[pi] * step, vah: ks[z] * step, val: ks[a] * step, va: [ks[a], ks[z]] };
    }
    // 호가 잔량
    const bk = this.book?.symbol === this.symbol ? this.book : null, bids = new Map(), asks = new Map();
    if (bk) {
      for (const x of bk.bids) { const k = key(x.price), o = bids.get(k) || { q: 0, u: 0 }; o.q += x.qty; o.u += x.usd; bids.set(k, o); }
      for (const x of bk.asks) { const k = key(x.price), o = asks.get(k) || { q: 0, u: 0 }; o.q += x.qty; o.u += x.usd; asks.set(k, o); }
    }
    const tags = new Map();
    for (const t of this._ladderTags(vis, vp)) { const k = key(t.price); if (!tags.has(k)) tags.set(k, []); if (!tags.get(k).some((x) => x.short === t.short)) tags.get(k).push(t); }
    const k0 = Math.floor(bot / step), k1 = Math.ceil(top / step);
    let vmax = 0, bmax = 0;
    for (let k = k0; k <= k1; k++) { vmax = Math.max(vmax, vol.get(k)?.v || 0); bmax = Math.max(bmax, bids.get(k)?.q || 0, asks.get(k)?.q || 0); }
    const font = getComputedStyle(document.body).fontFamily, mono = css("--mono");
    const up = css("--up"), down = css("--down"), cur = key(last.close), cross = this._crossY != null ? key(s.coordinateToPrice(this._crossY) ?? NaN) : null;
    // 열 경계: 가격 | 거래량 | 호가 | 표시 (좁은 칸이면 호가 열은 빼고 툴팁으로)
    const compact = W < 200, C1 = 62, C2 = compact ? 104 : 118, C3 = compact ? 104 : 164;
    ctx.textBaseline = "middle";
    for (let k = k0; k <= k1; k++) {
      const p = k * step, y = s.priceToCoordinate(p);
      if (y == null) continue;
      const y1 = s.priceToCoordinate(p + step / 2), y2 = s.priceToCoordinate(p - step / 2), h = Math.max(1, y2 - y1);
      if (y2 < 0 || y1 > H) continue;
      const v = vol.get(k), bd = bids.get(k), ak = asks.get(k), tg = tags.get(k) || [];
      this._ladRows.push({ price: p, y1, y2, vol: v?.v || 0, buy: v?.b || 0, bid: bd?.q, bidUsd: bd?.u, ask: ak?.q, askUsd: ak?.u, tags: tg });
      // 배경: 현재가 칸 / 십자선 칸 / 가치 영역
      if (k === cur) { ctx.fillStyle = last.close >= last.open ? "rgba(34,176,125,.28)" : "rgba(229,72,77,.28)"; ctx.fillRect(0, y1, W, h); }
      else if (k === cross) { ctx.fillStyle = "rgba(255,255,255,.08)"; ctx.fillRect(0, y1, W, h); }
      else if (vp && k >= vp.va[0] && k <= vp.va[1]) { ctx.fillStyle = "rgba(245,165,36,.04)"; ctx.fillRect(C1, y1, C2 - C1, h); }
      // 거래량 막대 (매수 초록 | 매도 빨강)
      if (v && vmax) {
        const w = (C2 - C1 - 4) * v.v / vmax, wb = w * (v.b / v.v || 0);
        ctx.fillStyle = "rgba(34,176,125,.55)"; ctx.fillRect(C1 + 2, y1 + 1, wb, h - 2);
        ctx.fillStyle = "rgba(229,72,77,.55)"; ctx.fillRect(C1 + 2 + wb, y1 + 1, w - wb, h - 2);
        if (vp && k === key(vp.poc)) { ctx.strokeStyle = "rgba(245,165,36,.9)"; ctx.strokeRect(C1 + 1.5, y1 + .5, C2 - C1 - 3, h - 1); }
      }
      // 호가 잔량 (현재가 아래 = 매수, 위 = 매도)
      const q = bd?.q || ak?.q;
      if (q && bmax && !compact) {
        const w = (C3 - C2 - 4) * q / bmax;
        ctx.fillStyle = bd ? "rgba(34,176,125,.3)" : "rgba(229,72,77,.3)"; ctx.fillRect(C3 - 2 - w, y1 + 1, w, h - 2);
        if (h >= 11) { ctx.font = `10px ${mono}`; ctx.fillStyle = bd ? up : down; ctx.textAlign = "right"; ctx.fillText(big(q), C3 - 3, y); }
      }
      // 가격
      if ((h >= 10 || tg.length || k === cur) && y > 20) {
        const round = Math.abs(p / (step * 10) - Math.round(p / (step * 10))) < 1e-6;
        ctx.font = `${round || k === cur ? "600 " : ""}10.5px ${mono}`; ctx.textAlign = "left";
        ctx.fillStyle = k === cur ? "#fff" : round ? css("--text") : css("--text-2");
        ctx.fillText(p.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec }), 4, y);
      }
      // 표시
      if (tg.length) {
        ctx.fillStyle = tg[0].color; ctx.fillRect(0, y1, 2, h);
        ctx.font = `600 9.5px ${font}`; ctx.textAlign = "left"; ctx.fillStyle = tg[0].color;
        ctx.fillText(tg[0].short + (tg.length > 1 ? "+" : ""), C3 + 3, y);
      }
    }
    // 열 구분선 · 머리글
    ctx.strokeStyle = "rgba(255,255,255,.06)"; ctx.beginPath();
    (compact ? [C1, C2] : [C1, C2, C3]).forEach((x) => { ctx.moveTo(x + .5, 0); ctx.lineTo(x + .5, H); }); ctx.stroke();
    ctx.fillStyle = css("--panel"); ctx.fillRect(0, 0, W, 15);
    ctx.font = `10px ${font}`; ctx.fillStyle = css("--muted"); ctx.textAlign = "center";
    [["가격", C1 / 2], ["거래량", (C1 + C2) / 2], ...(compact ? [] : [["호가", (C2 + C3) / 2]]), ["표시", (C3 + W) / 2]].forEach(([t, x]) => ctx.fillText(t, x, 8));
    ctx.fillStyle = css("--muted"); ctx.textAlign = "left"; ctx.fillRect(0, 15, W, .5);
    if (Hb > H) { ctx.font = `10px ${font}`; ctx.fillStyle = css("--muted"); ctx.fillText(`칸 ${step.toLocaleString("en-US", { maximumFractionDigits: 8 })}`, 4, H + 12); }
  }

  // ------------------------------------------------------------ 오버레이
  async refreshOverlays() {
    const o = this.opts.overlays, sym = this.symbol, iv = this.interval;
    const got = { heat: null, whales: null, markers: null, sr: null, ai: null, sbot: null };
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
    if (o.ai) jobs.push(api(`/api/aibot?symbol=${sym}&interval=${iv}`).then((d) => (got.ai = d)).catch(() => {}));
    if (o.sbot) jobs.push(api(`/api/scenbot/chart?symbol=${sym}&interval=${iv}`).then((d) => (got.sbot = d)).catch(() => {}));
    if (o.footprint) jobs.push(this.loadFootprint());
    await Promise.all(jobs);
    if (!this._is(sym, iv)) return;   // 기다리는 동안 코인·봉을 바꿨으면 이전 결과는 버린다
    Object.assign(this, got);
    this._applyMarkers();
    this.heatLayer.update(); this.whaleLayer.update(); this.srLayer.update();
    this._legend();
  }

  // 시나리오 봇 주문·포지션만 다시 (실시간 손익 · 몇 초마다)
  async refreshSbot() {
    if (!this.opts.overlays.sbot || !this.candles.length) return;
    const sym = this.symbol, iv = this.interval;
    let d;
    try { d = await api(`/api/scenbot/chart?symbol=${sym}&interval=${iv}`); } catch { return; }
    if (!this._is(sym, iv)) return;
    const key = JSON.stringify([d.orders, d.trades.length]);
    this.sbot = d;
    if (key !== this._sbKey) { this._sbKey = key; this._applyMarkers(); }
  }

  // AI 진입 시그널만 다시 (새 분석이 나왔을 때)
  async refreshAi() {
    if (!this.opts.overlays.ai || !this.candles.length) return;
    const sym = this.symbol, iv = this.interval;
    let d;
    try { d = await api(`/api/aibot?symbol=${sym}&interval=${iv}`); } catch { return; }
    if (!this._is(sym, iv)) return;
    this.ai = d; this._applyMarkers(); this._legend();
  }

  setOverlay(name, on) {
    this.opts.overlays[name] = on;
    if (name === "footprint") {
      if (!on) { this.fp = null; this.fpMarkers = []; this._pushMarkers(); this.fpLayer.update(); this._legend(); return; }
      const n = this.candles.length;   // 숫자가 보이도록 최근 12봉으로 확대
      if (n) this.chart.timeScale().setVisibleLogicalRange({ from: n - 12, to: n + 1 });
    }
    this.refreshOverlays();
  }

  async loadFootprint() {
    const sym = this.symbol, iv = this.interval;
    try {
      const f = await api(`/api/footprint?symbol=${sym}&interval=${iv}&bars=80&analysis=true`);
      if (!this._is(sym, iv) || !this.opts.overlays.footprint) return;
      f.byTime = new Map(f.bars.map((b) => [b.time, b]));
      this.fp = f;
      // 풋프린트 진입 신호 → 차트 화살표 (지난 신호는 결과 표시)
      this.fpMarkers = (f.analysis?.signals || []).map((sg) => ({ time: sg.time, position: sg.dir === "long" ? "belowBar" : "aboveBar",
        shape: sg.dir === "long" ? "arrowUp" : "arrowDown", color: sg.dir === "long" ? css("--up") : css("--down"),
        text: `FP ${sg.dir === "long" ? "롱" : "숏"}${sg.outcome === "take" ? " ✓" : sg.outcome === "stop" ? " ✗" : ""}` }));
      this.opts.onFootprint?.(f);
    } catch (e) { if (this._is(sym, iv)) { this.fp = { error: e.message }; this.fpMarkers = []; } }
    this._pushMarkers(); this.fpLayer.update(); this._legend();
  }

  // 봉 볼륨 풋프린트: 넓게 확대하면 칸마다 '매도 × 매수' 숫자, 좁으면 색으로
  _drawFootprint(ctx, size) {
    const f = this.fp;
    if (!f?.byTime) return;
    const ts = this.chart.timeScale(), bw = ts.options().barSpacing, range = ts.getVisibleLogicalRange();
    if (!range || bw < 5) return;
    const c = this.candles, font = getComputedStyle(document.body).fontFamily;
    const k = (v) => v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? (v / 1e3).toFixed(1) + "k" : v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toFixed(2);
    const numbers = bw >= 48;
    ctx.font = `${Math.min(11, Math.max(9, bw / 9))}px ${font}`; ctx.textBaseline = "middle";
    for (let i = Math.max(0, Math.floor(range.from)); i <= Math.min(c.length - 1, Math.ceil(range.to)); i++) {
      const b = f.byTime.get(c[i].time), x = ts.logicalToCoordinate(i);
      if (!b || x == null) continue;
      const half = bw * 0.46, mx = Math.max(...b.levels.map((l) => l[1] + l[2])) || 1;
      const ib = new Set(b.imb_buy), is = new Set(b.imb_sell);
      for (const [p, sell, buy] of b.levels) {
        const y1 = this.candle.priceToCoordinate(p + f.tick), y2 = this.candle.priceToCoordinate(p);
        if (y1 == null || y2 == null) continue;
        const h = Math.max(1, y2 - y1 - (numbers ? 1 : 0)), tot = sell + buy, d = tot ? (buy - sell) / tot : 0;
        if (numbers) {
          ctx.fillStyle = "rgba(18,22,28,.9)"; ctx.fillRect(x - half, y1, half * 2, h);
          ctx.fillStyle = d >= 0 ? `rgba(34,176,125,${0.12 + 0.5 * tot / mx})` : `rgba(229,72,77,${0.12 + 0.5 * tot / mx})`; ctx.fillRect(x - half, y1, half * 2, h);
          if (h >= 9) {
            ctx.textAlign = "right"; ctx.fillStyle = is.has(p) ? "#ff8a8d" : "rgba(230,232,234,.85)"; ctx.fillText(k(sell), x - 3, y1 + h / 2);
            ctx.textAlign = "left"; ctx.fillStyle = ib.has(p) ? "#5fe0a8" : "rgba(230,232,234,.85)"; ctx.fillText(k(buy), x + 3, y1 + h / 2);
            ctx.fillStyle = "rgba(164,172,182,.5)"; ctx.fillRect(x, y1 + 2, 1, h - 4);
          }
        } else {
          ctx.fillStyle = d >= 0 ? `rgba(34,176,125,${0.1 + 0.55 * tot / mx})` : `rgba(229,72,77,${0.1 + 0.55 * tot / mx})`;
          ctx.fillRect(x - half, y1, half * 2, h);
        }
        if (p === b.poc) { ctx.strokeStyle = "rgba(245,165,36,.95)"; ctx.lineWidth = 1; ctx.strokeRect(x - half + 0.5, y1 + 0.5, half * 2 - 1, h - 1); }
      }
      for (const z of b.stacked) {   // 연속 불균형 구간: 봉 옆 굵은 막대
        const ya = this.candle.priceToCoordinate(z.high), yb = this.candle.priceToCoordinate(z.low);
        if (ya == null || yb == null) continue;
        ctx.fillStyle = z.side === "buy" ? "#22b07d" : "#e5484d"; ctx.fillRect(z.side === "buy" ? x - half - 3 : x + half + 1, ya, 2, yb - ya);
      }
      if (bw >= 30) {   // 봉 아래 델타
        const y = this.candle.priceToCoordinate(b.low);
        if (y != null) { ctx.textAlign = "center"; ctx.fillStyle = b.delta >= 0 ? "#22b07d" : "#e5484d"; ctx.fillText(`Δ${b.delta >= 0 ? "+" : ""}${k(Math.abs(b.delta)).replace(/^/, b.delta < 0 ? "-" : "")}`, x, y + 10); }
      }
    }
    ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
    this._drawLevels(ctx, size);
  }

  // 지지·저항 판정 선 + 다음 봉 확률 상자
  _drawLevels(ctx, size) {
    const a = this.fp?.analysis;
    if (!a) return;
    const font = getComputedStyle(document.body).fontFamily;
    ctx.font = `10.5px ${font}`;
    const ST = { holding: "유지", weakening: "흔들림", broken: "이탈", untested: "미테스트" };
    for (const lv of a.levels.slice(0, 6)) {
      const y = this.candle.priceToCoordinate(lv.price);
      if (y == null) continue;
      const col = lv.status === "holding" ? (lv.role === "support" ? "rgba(34,176,125,.9)" : "rgba(229,72,77,.9)")
        : lv.status === "weakening" ? "rgba(245,165,36,.9)" : lv.status === "broken" ? "rgba(164,172,182,.7)" : "rgba(164,172,182,.45)";
      ctx.strokeStyle = col; ctx.lineWidth = lv.status === "holding" ? 1.5 : 1;
      ctx.setLineDash(lv.status === "holding" ? [] : lv.status === "weakening" ? [6, 3] : [2, 3]);
      ctx.beginPath(); ctx.moveTo(size.width * 0.35, y); ctx.lineTo(size.width, y); ctx.stroke(); ctx.setLineDash([]);
      const label = `${lv.role === "support" ? "지지" : "저항"} ${ST[lv.status]} · ${lv.source.split(" · ")[0]}${lv.touches ? ` · ${lv.touches}회` : ""}`;
      const w = ctx.measureText(label).width + 8;
      ctx.fillStyle = "rgba(18,22,28,.85)"; ctx.fillRect(size.width * 0.35, y - 13, w, 12);
      ctx.fillStyle = col; ctx.fillText(label, size.width * 0.35 + 4, y - 4);
    }
    const n = a.next?.forming, ts = this.chart.timeScale(), last = this.candles.at(-1);
    const x = last ? ts.timeToCoordinate(last.time) : null;
    if (n?.p_up != null && x != null) {
      const up = n.p_up >= 50, txt = `다음 봉 ${up ? "▲" : "▼"} ${up ? n.p_up : 100 - n.p_up}% (같은 모양 ${n.n}번)`;
      const w = ctx.measureText(txt).width + 10, bx = Math.min(size.width - w - 4, x + 14), by = 8;
      ctx.fillStyle = "rgba(18,22,28,.92)"; ctx.fillRect(bx, by, w, 18);
      ctx.strokeStyle = up ? "rgba(34,176,125,.9)" : "rgba(229,72,77,.9)"; ctx.strokeRect(bx + 0.5, by + 0.5, w - 1, 17);
      ctx.fillStyle = up ? "#5fe0a8" : "#ff8a8d"; ctx.fillText(txt, bx + 5, by + 13);
    }
  }

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
    if (this.opts.overlays.ai && this.ai?.signals?.length) {
      // AI 시그널(보라 점) → AI 봇 진입(🤖 화살표) → 청산(익절·손절 수익률). 보유 중이면 AI 봇 진입·손절·익절선, 대기 중이면 대기 진입선
      const AIC = "#9d7bff", sgn = (v) => (v > 0 ? "+" : "");
      const n = this.ai.signals.length;
      this.ai.signals.forEach((x, i) => {
        const long = x.side === "long", who = x.engine === "rules" ? "규칙" : "AI", t0 = this._barTime(x.bar_time), tr = x.trade, recent = i >= n - 3;
        if (t0 && !tr) mk.push({ time: t0, position: long ? "belowBar" : "aboveBar", shape: "circle", size: 0.6, color: AIC,
          text: recent ? `${who} ${long ? "롱" : "숏"} 신호 · ${x.skip ? "건너뜀" : x.outcome?.label || ""}` : "" });
        if (!tr) return;
        const te = this._barTime(tr.entry_time), tx = tr.exit_time && this._barTime(tr.exit_time);
        if (te) mk.push({ time: te, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown", color: AIC,
          text: `🤖${long ? "롱" : "숏"}${recent && x.confidence != null ? ` ${x.confidence}%` : ""}` });
        if (tx) mk.push({ time: tx, position: long ? "aboveBar" : "belowBar", shape: "circle", color: tr.pnl > 0 ? css("--up") : css("--down"),
          text: `${tr.label} ${sgn(tr.roe_pct)}${tr.roe_pct.toFixed(1)}%` });
      });
      const open = this.ai.open?.[this.ai.open.length - 1];
      if (open) {
        line(open.entry, `🤖 AI봇 ${open.side === "long" ? "롱" : "숏"} 보유 ${open.roe_pct >= 0 ? "+" : ""}${open.roe_pct.toFixed(1)}%`, AIC, 0);
        line(open.stop, "🤖 AI봇 손절", css("--down")); line(open.take, "🤖 AI봇 익절", css("--up"));
      } else {
        const wait = [...this.ai.signals].reverse().find((x) => x.outcome?.status === "waiting" && !x.skip);
        if (wait) {
          const who = wait.engine === "rules" ? "규칙" : "AI";
          line(wait.entry, `${who} ${wait.side === "long" ? "롱" : "숏"} 진입 대기`, AIC, 2); line(wait.stop, `${who} 손절`, css("--down"), 3); line(wait.take, `${who} 익절`, css("--up"), 3);
        }
      }
    }
    if (this.opts.overlays.sbot && this.sbot?.symbol === this.symbol) {
      // 시나리오 봇: 지난 진입(주황 화살표) → 청산(목표/손절 · 증거금 대비 %) · 보유 중이면 진입·손절·목표·청산가 + 실시간 수익률 · 대기 중이면 주문선
      const SB = "#ff9f43", pc = (v) => `${v > 0 ? "+" : ""}${(+v || 0).toFixed(1)}%`;
      const iv = this.interval, same = (x) => x.interval === iv;
      const trades = this.sbot.trades.filter(same), nT = trades.length;
      trades.forEach((t, i) => {
        const long = t.side > 0, te = this._barTime(t.entry_time), tx = this._barTime(t.exit_time), recent = i >= nT - 6;
        if (te) mk.push({ time: te, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown", color: SB,
          text: recent ? `시나리오 ${long ? "롱" : "숏"} ${t.lev}배` : "" });
        if (tx) mk.push({ time: tx, position: long ? "aboveBar" : "belowBar", shape: "circle", color: t.pnl > 0 ? css("--up") : css("--down"),
          text: recent ? `${t.exit === "target" ? "목표" : t.exit === "stop" ? "손절" : "시간"} ${pc(t.roe_pct)}` : "" });
      });
      this.sbot.orders.filter(same).forEach((o) => {
        const long = o.side > 0, d = long ? "롱" : "숏";
        if (o.status === "open") {
          const te = this._barTime(o.filled_at);
          if (te) mk.push({ time: te, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown", color: SB, text: `시나리오 ${d} 진입` });
          line(o.entry, `🤖 시나리오봇 ${d} ${o.lev}배 ${o.roe_pct != null ? pc(o.roe_pct) : ""}${o.upnl != null ? ` (${o.upnl > 0 ? "+" : ""}${fmt(o.upnl, 2)})` : ""}`, SB, 0);
          line(o.stop, "🤖 봇 손절", css("--down")); line(o.tp, "🤖 봇 목표", css("--up")); line(o.liq, "🤖 봇 청산가", "rgba(229,72,77,.5)", 3);
        } else {
          line(o.entry, `🤖 시나리오봇 ${d} 대기 (${o.order === "stop" ? "돌파 시" : "지정가"} · ${o.title})`, SB, 2);
          line(o.stop, "🤖 봇 손절", css("--down"), 3); line(o.tp, "🤖 봇 목표", css("--up"), 3);
        }
      });
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
    const mk = [...(this._baseMarkers || []), ...(this.sigMarkers || []), ...(this.fpMarkers || [])];
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
  _pos() { return null; }      // 분석 전용 — 모의 주문 포지션 없음
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

  // ------------------------------------------------------------ 차트 종류 · 가격축 · 기간 · 스크린샷 (트레이딩뷰 방식)
  setChartType(t) { this.ctype = t; this._display(); }
  _display() {
    const t = this.ctype || "candles", c = this.candles, up = css("--up"), dn = css("--down"), clear = "rgba(0,0,0,0)";
    const own = ["candles", "hollow", "ha"].includes(t);
    if (t === "hollow") this.candle.applyOptions({ upColor: clear, downColor: dn, borderVisible: true, borderUpColor: up, borderDownColor: dn, wickUpColor: up, wickDownColor: dn, lastValueVisible: true, priceLineVisible: true });
    else if (own) this.candle.applyOptions({ upColor: up, downColor: dn, borderVisible: false, wickUpColor: up, wickDownColor: dn, lastValueVisible: true, priceLineVisible: true });
    else this.candle.applyOptions({ upColor: clear, downColor: clear, borderVisible: false, wickUpColor: clear, wickDownColor: clear, lastValueVisible: false, priceLineVisible: false });
    this.candle.setData(t === "ha" ? heikinAshi(c) : c);
    if (this.dispType !== t) {
      if (this.disp) { try { this.chart.removeSeries(this.disp); } catch { /* 무시 */ } this.disp = null; }
      this.dispType = t;
      const blue = "#2962ff";
      if (t === "bars") this.disp = this.chart.addSeries(LC.BarSeries, { upColor: up, downColor: dn, thinBars: false }, 0);
      else if (t === "line") this.disp = this.chart.addSeries(LC.LineSeries, { color: blue, lineWidth: 2 }, 0);
      else if (t === "area") this.disp = this.chart.addSeries(LC.AreaSeries, { lineColor: blue, topColor: "rgba(41,98,255,.35)", bottomColor: "rgba(41,98,255,0)", lineWidth: 2 }, 0);
      else if (t === "baseline") this.disp = this.chart.addSeries(LC.BaselineSeries, { baseValue: { type: "price", price: c[Math.floor(c.length / 2)]?.close || 0 },
        topLineColor: up, bottomLineColor: dn, topFillColor1: "rgba(8,153,129,.28)", topFillColor2: "rgba(8,153,129,.05)", bottomFillColor1: "rgba(242,54,69,.05)", bottomFillColor2: "rgba(242,54,69,.28)" }, 0);
    }
    if (this.disp) this.disp.setData(t === "bars" ? c : c.map((b) => ({ time: b.time, value: b.close })));
  }
  setScale({ mode, auto }) {
    const M = { normal: 0, log: 1, pct: 2, idx: 3 };
    this.chart.priceScale("right").applyOptions({ ...(mode ? { mode: M[mode] ?? 0 } : {}), ...(auto != null ? { autoScale: auto } : {}) });
  }
  showSeconds(sec) {
    const c = this.candles;
    if (!c.length) return;
    const to = c.at(-1).time, from = sec ? Math.max(c[0].time, to - sec) : c[0].time;
    try { this.chart.timeScale().setVisibleRange({ from, to }); } catch { this.chart.timeScale().fitContent(); }
  }
  screenshot() {
    const cv = this.chart.takeScreenshot(), ctx = cv.getContext("2d");
    const b = this.candles.at(-1);
    ctx.font = "bold 14px " + getComputedStyle(document.body).fontFamily;
    ctx.fillStyle = "#d1d4dc";
    ctx.fillText(`${this.symbol} · ${IV_LABEL[this.interval] || this.interval} · ${b ? px(b.close) : ""} · GH Quant · ${new Date().toLocaleString("ko-KR")}`, 10, 20);
    return cv;
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
    const vals = (it) => it.last.plots.filter((pl) => !["signals", "boxes", "profiles", "patterns"].includes(pl.type) && pl.legend !== false).map((pl) => val(pl.data[idx])).join(" ");
    const extra = (it) => it.profile && this.vp ? ` <span class="muted">POC</span> ${px(this.vp.poc)} <span class="muted">가치영역</span> ${px(this.vp.val)}~${px(this.vp.vah)}`
      : it.last.note ? ` <span class="muted">${esc(it.last.note)}</span>` : "";
    const acts = (it) => `<span class="lg-act"><button data-lg="hide" data-ii="${this.indicators.indexOf(it.spec)}" title="${it.spec.hidden ? "보이기" : "숨기기"}">${it.spec.hidden ? "◌" : "◉"}</button><button data-lg="set" data-ii="${this.indicators.indexOf(it.spec)}" title="설정">⚙</button><button data-lg="del" data-ii="${this.indicators.indexOf(it.spec)}" title="지우기">✕</button></span>`;
    if (mainInd.length) html += mainInd.map((it) => `<div class="lg-row ${it.spec.hidden ? "off" : ""}"><span style="color:${it.last.plots.find((pl) => pl.color)?.color || "inherit"}">${esc(INDICATORS[it.spec.key].name)}${paramStr(it.params)}</span> ${it.spec.hidden ? "" : vals(it) + extra(it)}${acts(it)}</div>`).join("");
    if (this.opts.overlays.footprint && this.fp) html += `<br><span class="muted">풋프린트: ${this.fp.error ? esc(this.fp.error) : `${this.fp.sub_interval} 봉 체결로 근사 · 칸 ${px(this.fp.tick)} · 왼쪽 매도 × 오른쪽 매수 · 주황 테두리 = 봉 POC · 초록/빨강 숫자 = 3배 불균형${ts_hint(this)}`}</span>`;
    if (this.heat) html += `<br><span class="muted">청산맵: ${this.heat.model === "coinglass" ? "CoinGlass" : this.heat.model === "estimate_oi" ? "OI 기반 추정" : "거래대금 기반 추정"}</span> <span class="scale"></span>`;
    if (this.whales) html += `<br><span class="muted">고래 체결 ≥ $${big(this.whales.min_usd)} · ${this.whales.trades.length}건${this.whales.source === "binance" && this.whales.collecting_since ? " (프로그램 실행 후 수집분)" : ""} · 호가벽 ${this.whales.walls.length}개</span>`;
    html += `</div>`;
    for (const it of this.ind.filter((x) => x.pane > 0)) {
      const top = tops[it.pane];
      if (top == null) continue;
      html += `<div class="lg-row lg-sub" style="top:${top + 3}px"><span class="dim">${esc(INDICATORS[it.spec.key].name)}${paramStr(it.params)}</span>${acts(it)} ${it.last.plots.filter((pl) => !["signals", "boxes", "profiles", "patterns"].includes(pl.type) && pl.legend !== false).map((pl) => `<span style="color:${pl.color || "inherit"}">${val(pl.data[idx])}</span>`).join(" ")}${it.last.note ? ` <span class="accent">${esc(it.last.note)}</span>` : ""}</div>`;
    }
    this.legendEl.innerHTML = html;
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

const ts_hint = (tc) => tc.chart.timeScale().options().barSpacing < 48 ? " · 더 확대하면 숫자가 보입니다" : "";
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

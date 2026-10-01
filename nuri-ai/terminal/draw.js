// 그리기 도구 (트레이딩뷰 방식) — 추세선 · 레이 · 연장선 · 수평선/수평 레이 · 수직선 · 평행 채널 · 피보나치 되돌림/확장 ·
// 사각형 · 화살표 · 텍스트 · 롱/숏 포지션 도구 · 가격 범위 · 날짜·가격 범위 · 브러시
// 차트와 같이 확대/이동되고, 종목마다 localStorage 에 저장된다(모든 봉 간격에서 같이 보임). 선택 → 끌어서 이동 · 점 끌어서 수정 · Delete 로 삭제 ·
// Ctrl+Z / Ctrl+Y 되돌리기 · 자석(봉의 시가/고가/저가/종가에 붙기) · 잠금 · 모두 숨기기.
// 원본: GH Quant frontend/js/draw.js (누리 터미널용: 저장 키 · 활성 칸 판정 · 가격 자릿수만 바꿈)
import { Layer } from "./chart.js";

export const TOOLS = {
  cursor: { name: "커서", pts: 0 },
  trend: { name: "추세선", pts: 2 }, ray: { name: "레이", pts: 2 }, extended: { name: "연장선", pts: 2 },
  hline: { name: "수평선", pts: 1 }, hray: { name: "수평 레이", pts: 1 }, vline: { name: "수직선", pts: 1 },
  channel: { name: "평행 채널", pts: 3 }, fib: { name: "피보나치 되돌림", pts: 2 }, fibext: { name: "피보나치 확장", pts: 3 },
  rect: { name: "사각형", pts: 2 }, arrow: { name: "화살표", pts: 2 }, text: { name: "텍스트", pts: 1 },
  long: { name: "롱 포지션", pts: 1 }, short: { name: "숏 포지션", pts: 1 },
  range: { name: "가격 범위", pts: 2 }, daterange: { name: "날짜·가격 범위", pts: 2 }, brush: { name: "브러시", pts: -1 },
};
const COLORS = ["#2962ff", "#f23645", "#089981", "#ff9800", "#9c27b0", "#00bcd4", "#e0e3eb", "#ffeb3b"];
const DEF_COLOR = { long: "#089981", short: "#f23645", fib: "#787b86", fibext: "#787b86", range: "#2962ff", daterange: "#2962ff", channel: "#2962ff", rect: "#9c27b0", text: "#e0e3eb" };
const FIB = [[0, "#787b86"], [0.236, "#f23645"], [0.382, "#ff9800"], [0.5, "#4caf50"], [0.618, "#089981"], [0.786, "#00bcd4"], [1, "#787b86"], [1.618, "#2962ff"]];
const FIBEXT = [[0, "#787b86"], [0.618, "#f23645"], [1, "#089981"], [1.272, "#ff9800"], [1.618, "#2962ff"], [2.618, "#9c27b0"]];
const uid = () => Math.random().toString(36).slice(2, 9);

export class Drawings {
  constructor(tc, { onChange } = {}) {
    this.tc = tc;
    this.onChange = onChange || (() => {});
    this.items = []; this.sel = null; this.tool = "cursor"; this.temp = null;
    this.undo = []; this.redo = [];
    this.magnet = false; this.locked = false; this.hidden = false; this.stay = false;
    this.layer = new Layer((ctx, size) => this.draw(ctx, size), "top");
    tc.candle.attachPrimitive(this.layer);
    this._bind();
  }

  // ------------------------------------------------------------ 좌표 변환 (봉 밖 미래 구간도)
  _step() { const c = this.tc.candles; return c.length > 1 ? c.at(-1).time - c.at(-2).time : 3600; }
  t2x(t) {
    const c = this.tc.candles, ts = this.tc.chart.timeScale();
    if (!c.length) return null;
    const step = this._step();
    let l;
    if (t >= c.at(-1).time) l = c.length - 1 + (t - c.at(-1).time) / step;
    else if (t <= c[0].time) l = (t - c[0].time) / step;
    else {
      let lo = 0, hi = c.length - 1;
      while (lo < hi) { const m = (lo + hi + 1) >> 1; if (c[m].time <= t) lo = m; else hi = m - 1; }
      const span = (c[lo + 1]?.time ?? c[lo].time + step) - c[lo].time;
      l = lo + (t - c[lo].time) / (span || step);
    }
    return ts.logicalToCoordinate(l);
  }
  x2t(x) {
    const c = this.tc.candles, ts = this.tc.chart.timeScale();
    const l = ts.coordinateToLogical(x);
    if (l == null || !c.length) return null;
    const step = this._step();
    if (l >= c.length - 1) return Math.round(c.at(-1).time + (l - (c.length - 1)) * step);
    if (l <= 0) return Math.round(c[0].time + l * step);
    const i = Math.floor(l);
    return Math.round(c[i].time + (l - i) * ((c[i + 1]?.time ?? c[i].time + step) - c[i].time));
  }
  p2y(p) { return this.tc.candle.priceToCoordinate(p); }
  y2p(y) { return this.tc.candle.coordinateToPrice(y); }
  _pt(e, snap = true) {
    const r = this.tc.chart.chartElement().getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    let t = this.x2t(x), p = this.y2p(y);
    if (snap && (this.magnet || e.ctrlKey) && t != null) {          // 자석: 가까운 봉의 OHLC 에 붙임
      const c = this.tc.candles, ts = this.tc.chart.timeScale();
      const l = Math.round(ts.coordinateToLogical(x));
      const b = c[Math.max(0, Math.min(c.length - 1, l))];
      if (b) {
        const best = ["open", "high", "low", "close"].map((k) => [k, Math.abs(this.p2y(b[k]) - y)]).sort((a, b2) => a[1] - b2[1])[0];
        if (best[1] < 30) { p = b[best[0]]; t = b.time; }
      }
    }
    return { t, p, x, y };
  }

  // ------------------------------------------------------------ 저장 · 되돌리기
  _key() { return `nuri:term:draw:${this.tc.exchange}:${this.tc.symbol}`; }
  load() {
    this.sel = null; this.temp = null; this.undo = []; this.redo = [];
    try { this.items = JSON.parse(localStorage.getItem(this._key()) || "null"); } catch { this.items = null; }
    if (!Array.isArray(this.items)) this.items = [];
    this.layer.update(); this.onChange();
  }
  _save() { try { localStorage.setItem(this._key(), JSON.stringify(this.items)); } catch { /* 무시 */ } this.onChange(); }
  _snap() { this.undo.push(JSON.stringify(this.items)); if (this.undo.length > 100) this.undo.shift(); this.redo = []; }
  doUndo() { if (!this.undo.length) return; this.redo.push(JSON.stringify(this.items)); this.items = JSON.parse(this.undo.pop()); this.sel = null; this._save(); this.layer.update(); }
  doRedo() { if (!this.redo.length) return; this.undo.push(JSON.stringify(this.items)); this.items = JSON.parse(this.redo.pop()); this.sel = null; this._save(); this.layer.update(); }

  setTool(t) {
    this.tool = TOOLS[t] ? t : "cursor"; this.temp = null;
    this.tc.el.style.cursor = this.tool === "cursor" ? "" : "crosshair";
    this.layer.update(); this.onChange();
  }
  remove(id) { this._snap(); this.items = this.items.filter((d) => d.id !== (id ?? this.sel)); if (this.sel === id || id == null) this.sel = null; this._save(); this.layer.update(); }
  clear() { if (!this.items.length) return; this._snap(); this.items = []; this.sel = null; this._save(); this.layer.update(); }
  select(id) { this.sel = id; this.layer.update(); this.onChange(); }
  toggle(id, key) { const d = this.items.find((x) => x.id === id); if (!d) return; this._snap(); d[key] = !d[key]; this._save(); this.layer.update(); }
  style(patch) { const d = this.items.find((x) => x.id === this.sel); if (!d) return; this._snap(); Object.assign(d, patch); this._save(); this.layer.update(); }
  selected() { return this.items.find((x) => x.id === this.sel) || null; }
  list() { return this.items.map((d) => ({ id: d.id, type: d.type, name: TOOLS[d.type]?.name || d.type, hidden: !!d.hidden, locked: !!d.locked, text: d.text })); }

  // ------------------------------------------------------------ 마우스
  _bind() {
    const box = this.tc.el;
    const busy = (on) => this.tc.chart.applyOptions({ handleScroll: !on, handleScale: !on });
    const inPlot = (e) => {
      const r = this.tc.chart.chartElement().getBoundingClientRect();
      const ps = this.tc.chart.priceScale("right").width();
      return e.clientX - r.left < r.width - ps && e.clientY - r.top < r.height - this.tc.chart.timeScale().height();
    };
    box.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || !inPlot(e) || this.hidden) return;
      const pt = this._pt(e);
      if (pt.t == null || pt.p == null) return;
      if (this.tool !== "cursor") {
        e.stopPropagation(); e.preventDefault(); busy(true);
        this._create(pt, e);
        return;
      }
      const hit = this._hit(pt.x, pt.y);
      if (!hit) { if (this.sel) { this.sel = null; this.layer.update(); this.onChange(); } return; }
      this.sel = hit.d.id; this.onChange();
      if (this.locked || hit.d.locked) { this.layer.update(); return; }
      e.stopPropagation(); e.preventDefault(); busy(true);
      this._snap();
      this.drag = { d: hit.d, k: hit.k, start: pt, orig: JSON.parse(JSON.stringify(hit.d.pts)) };
      this.layer.update();
    }, true);
    box.addEventListener("pointermove", (e) => {
      if (this.temp) {
        const pt = this._pt(e);
        if (pt.t == null) return;
        if (this.temp.type === "brush") { if (this.temp.drawing) this.temp.pts.push({ t: pt.t, p: pt.p }); }
        else this.temp.pts[this.temp.n] = { t: pt.t, p: pt.p };
        this.temp.moved = true;
        this.layer.update();
        return;
      }
      if (this.drag) {
        const pt = this._pt(e, this.drag.k != null);
        if (pt.t == null) return;
        const { d, k, start, orig } = this.drag;
        if (k == null) {                                             // 통째로 이동
          const dt = pt.t - start.t, dp = pt.p - start.p;
          d.pts = orig.map((q) => ({ t: q.t + dt, p: q.p + dp }));
        } else d.pts[k] = { t: pt.t, p: pt.p };
        this.layer.update();
        return;
      }
      if (this.tool === "cursor" && inPlot(e)) {
        const pt = this._pt(e, false);
        const h = this._hit(pt.x, pt.y);
        box.style.cursor = h ? (h.k != null ? "move" : "pointer") : "";
      }
    }, true);
    const up = (e) => {
      if (this.drag) {
        this.drag = null; busy(false); this._save();
        return;
      }
      const tp = this.temp;
      if (!tp) return;
      if (tp.type === "brush") { tp.drawing = false; if (tp.pts.length > 1) this._commit(); else this.temp = null; busy(false); return; }
      if (tp.moved && tp.n === 1 && TOOLS[tp.type].pts === 2 && tp.dragStart) {     // 끌어서 그리기
        const d = Math.hypot((e.clientX - tp.dragStart.x), (e.clientY - tp.dragStart.y));
        if (d > 6) this._commit();
      }
    };
    window.addEventListener("pointerup", up);
    box.addEventListener("dblclick", (e) => {
      if (this.tool !== "cursor" || !inPlot(e)) return;
      const pt = this._pt(e, false), h = this._hit(pt.x, pt.y);
      if (h?.d.type === "text" && !h.d.locked) {
        const s = prompt("텍스트", h.d.text || "");
        if (s != null) { this._snap(); h.d.text = s; this._save(); this.layer.update(); }
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.target.closest?.("input, textarea, select") || !this.tc.el.isConnected || !(this.tc.opts.isActive?.(this.tc) ?? true)) return;
      if ((e.key === "Delete" || e.key === "Backspace") && this.sel) { e.preventDefault(); this.remove(this.sel); }
      else if (e.key === "Escape" && (this.tool !== "cursor" || this.temp)) { e.preventDefault(); e.stopImmediatePropagation(); this.temp = null; this.setTool("cursor"); busy(false); }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? this.doRedo() : this.doUndo(); }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); this.doRedo(); }
    });
  }

  _create(pt, e) {
    const type = this.tool, need = TOOLS[type].pts;
    const p0 = { t: pt.t, p: pt.p };
    if (this.temp && this.temp.type === type) {                      // 여러 점 도구의 다음 클릭
      this.temp.pts[this.temp.n] = p0;
      this.temp.n += 1;
      if (this.temp.n >= need) this._commit();
      else { this.temp.pts[this.temp.n] = { ...p0 }; this.layer.update(); }
      return;
    }
    const color = DEF_COLOR[type] || "#2962ff";
    if (type === "brush") { this.temp = { type, pts: [p0], drawing: true, color, width: 2 }; return; }
    if (need === 1) {
      const d = { id: uid(), type, pts: [p0], color, width: type === "hline" || type === "hray" || type === "vline" ? 1 : 2 };
      if (type === "text") { const s = prompt("텍스트", ""); if (!s) { this._done(); return; } d.text = s; }
      if (type === "long" || type === "short") {                     // 진입 · 손절 · 목표 · 오른쪽 끝 (ATR 기준 기본값)
        const c = this.tc.candles, atr = c.slice(-15).reduce((s, b) => s + (b.high - b.low), 0) / Math.max(1, Math.min(15, c.length));
        const sgn = type === "long" ? 1 : -1, step = this._step();
        d.pts = [p0, { t: p0.t, p: p0.p - sgn * atr * 1.5 }, { t: p0.t, p: p0.p + sgn * atr * 3 }, { t: p0.t + step * 20, p: p0.p }];
      }
      this._snap(); this.items.push(d); this.sel = d.id; this._save(); this._done();
      return;
    }
    this.temp = { type, pts: [p0, { ...p0 }], n: 1, color, width: 2, dragStart: { x: e.clientX, y: e.clientY } };
    this.layer.update();
  }
  _commit() {
    const tp = this.temp;
    this.temp = null;
    const d = { id: uid(), type: tp.type, pts: tp.pts.slice(0, Math.max(TOOLS[tp.type].pts, tp.pts.length)), color: tp.color, width: tp.width };
    this._snap(); this.items.push(d); this.sel = d.id; this._save(); this._done();
  }
  _done() {
    this.tc.chart.applyOptions({ handleScroll: true, handleScale: true });
    if (!this.stay) this.setTool("cursor"); else this.layer.update();
  }

  // ------------------------------------------------------------ 맞추기 (선택)
  _xy(d) { return d.pts.map((q) => [d.type === "hline" || d.type === "hray" ? (d.type === "hline" ? 0 : this.t2x(q.t)) : this.t2x(q.t), this.p2y(q.p)]); }
  _hit(x, y) {
    const near = (ax, ay) => ax != null && ay != null && Math.hypot(ax - x, ay - y) < 7;
    const seg = (x1, y1, x2, y2) => {
      if ([x1, y1, x2, y2].some((v) => v == null)) return false;
      const L = Math.hypot(x2 - x1, y2 - y1) || 1, u = ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / (L * L);
      const cu = Math.max(0, Math.min(1, u));
      return Math.hypot(x1 + cu * (x2 - x1) - x, y1 + cu * (y2 - y1) - y) < 6;
    };
    const W = this._w || 2000, H = this._h || 2000;
    for (let i = this.items.length - 1; i >= 0; i--) {
      const d = this.items[i];
      if (d.hidden) continue;
      const P = this._xy(d);
      const k = d.type === "hline" ? null : P.findIndex(([ax, ay]) => near(ax, ay));
      if (k != null && k >= 0 && d.type !== "brush") return { d, k };
      const [[x1, y1] = [], [x2, y2] = []] = P;
      switch (d.type) {
        case "hline": if (y1 != null && Math.abs(y1 - y) < 6) return { d, k: null }; break;
        case "hray": if (y1 != null && x >= x1 - 4 && Math.abs(y1 - y) < 6) return { d, k: null }; break;
        case "vline": if (x1 != null && Math.abs(x1 - x) < 6) return { d, k: null }; break;
        case "trend": case "arrow": if (seg(x1, y1, x2, y2)) return { d, k: null }; break;
        case "ray": case "extended": {
          const [a, b] = this._extend(x1, y1, x2, y2, W, d.type === "extended");
          if (a && seg(a[0], a[1], b[0], b[1])) return { d, k: null }; break;
        }
        case "rect": case "range": case "daterange": case "fib": case "fibext": case "channel": case "long": case "short": {
          const xs = P.map((q) => q[0]).filter((v) => v != null), ys = this._yRange(d);
          if (d.type === "long" || d.type === "short") xs.push(this.t2x(d.pts[3]?.t));
          if (x >= Math.min(...xs) - 4 && x <= Math.max(...xs) + 4 && y >= ys[0] - 4 && y <= ys[1] + 4) return { d, k: null }; break;
        }
        case "text": if (x1 != null && x >= x1 - 4 && x <= x1 + (d.text || "").length * 8 + 10 && y >= y1 - 16 && y <= y1 + 4) return { d, k: null }; break;
        case "brush": for (let j = 1; j < P.length; j++) if (seg(P[j - 1][0], P[j - 1][1], P[j][0], P[j][1])) return { d, k: null }; break;
        default: break;
      }
    }
    void H;
    return null;
  }
  _yRange(d) {
    if (d.type === "channel" && d.pts.length >= 3) {
      const off = d.pts[2].p - this._lineP(d.pts[0], d.pts[1], d.pts[2].t);
      const ys = [d.pts[0].p, d.pts[1].p, d.pts[0].p + off, d.pts[1].p + off].map((p) => this.p2y(p));
      return [Math.min(...ys), Math.max(...ys)];
    }
    if (d.type === "fib" || d.type === "fibext") {
      const lv = this._fibLevels(d).map(([, p]) => this.p2y(p));
      return [Math.min(...lv), Math.max(...lv)];
    }
    const ys = d.pts.slice(0, d.type === "long" || d.type === "short" ? 3 : 2).map((q) => this.p2y(q.p));
    return [Math.min(...ys), Math.max(...ys)];
  }
  _lineP(a, b, t) { return b.t === a.t ? a.p : a.p + (b.p - a.p) * (t - a.t) / (b.t - a.t); }
  _extend(x1, y1, x2, y2, W, both) {
    if ([x1, y1, x2, y2].some((v) => v == null)) return [null, null];
    const dx = x2 - x1, dy = y2 - y1;
    if (!dx && !dy) return [[x1, y1], [x2, y2]];
    const k = 5000 / (Math.hypot(dx, dy) || 1);
    return [both ? [x1 - dx * k, y1 - dy * k] : [x1, y1], [x2 + dx * k, y2 + dy * k]];
  }
  _fibLevels(d) {
    if (d.type === "fibext" && d.pts.length >= 3) {
      const [a, b, c] = d.pts, move = b.p - a.p;
      return FIBEXT.map(([r, col]) => [r, c.p + move * r, col]);
    }
    const [a, b] = d.pts;
    return FIB.map(([r, col]) => [r, b.p + (a.p - b.p) * r, col]);
  }

  // ------------------------------------------------------------ 그리기
  draw(ctx, size) {
    this._w = size.width; this._h = size.height;
    if (this.hidden) return;
    const font = getComputedStyle(document.body).fontFamily;
    ctx.font = `11px ${font}`; ctx.textBaseline = "alphabetic";
    const all = this.temp ? [...this.items, { ...this.temp, id: "_temp" }] : this.items;
    for (const d of all) {
      if (d.hidden) continue;
      try { this._one(ctx, size, d); } catch { /* 화면 밖 등 */ }
    }
  }
  _label(ctx, text, x, y, bg, fg = "#fff", align = "left") {
    const w = ctx.measureText(text).width + 8, h = 16;
    const lx = align === "right" ? x - w : align === "center" ? x - w / 2 : x;
    ctx.fillStyle = bg; ctx.beginPath(); ctx.roundRect?.(lx, y - h + 3, w, h, 3); ctx.fill();
    ctx.fillStyle = fg; ctx.fillText(text, lx + 4, y - 2);
  }
  _one(ctx, size, d) {
    const sel = d.id === this.sel, P = this._xy(d), W = size.width, H = size.height;
    const [[x1, y1] = [], [x2, y2] = []] = P;
    ctx.strokeStyle = d.color; ctx.fillStyle = d.color; ctx.lineWidth = d.width || 2; ctx.setLineDash(d.dash ? [6, 4] : []);
    const line = (a, b, c, e) => { ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c, e); ctx.stroke(); };
    const alpha = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
    switch (d.type) {
      case "trend": line(x1, y1, x2, y2); break;
      case "arrow": {
        line(x1, y1, x2, y2);
        const ang = Math.atan2(y2 - y1, x2 - x1), s = 10;
        ctx.beginPath(); ctx.moveTo(x2, y2); ctx.lineTo(x2 - s * Math.cos(ang - 0.4), y2 - s * Math.sin(ang - 0.4));
        ctx.lineTo(x2 - s * Math.cos(ang + 0.4), y2 - s * Math.sin(ang + 0.4)); ctx.closePath(); ctx.fill(); break;
      }
      case "ray": case "extended": { const [a, b] = this._extend(x1, y1, x2, y2, W, d.type === "extended"); if (a) line(a[0], a[1], b[0], b[1]); break; }
      case "hline": line(0, y1, W, y1); this._label(ctx, this.tc.px(d.pts[0].p), W - 2, y1 + 8, d.color, "#fff", "right"); break;
      case "hray": line(x1, y1, W, y1); this._label(ctx, this.tc.px(d.pts[0].p), W - 2, y1 + 8, d.color, "#fff", "right"); break;
      case "vline": line(x1, 0, x1, H); break;
      case "rect": ctx.fillStyle = alpha(d.color, 0.15); ctx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1)); ctx.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1)); break;
      case "channel": {
        line(x1, y1, x2, y2);
        if (d.pts.length >= 3) {
          const off = d.pts[2].p - this._lineP(d.pts[0], d.pts[1], d.pts[2].t);
          const y1b = this.p2y(d.pts[0].p + off), y2b = this.p2y(d.pts[1].p + off);
          line(x1, y1b, x2, y2b);
          ctx.setLineDash([4, 4]); line(x1, (y1 + y1b) / 2, x2, (y2 + y2b) / 2); ctx.setLineDash([]);
          ctx.fillStyle = alpha(d.color, 0.1); ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.lineTo(x2, y2b); ctx.lineTo(x1, y1b); ctx.closePath(); ctx.fill();
        }
        break;
      }
      case "fib": case "fibext": {
        const lv = this._fibLevels(d), xa = Math.min(...P.map((q) => q[0])), xb = Math.max(...P.map((q) => q[0])) + 60;
        lv.forEach(([r, p, col], i) => {
          const y = this.p2y(p);
          if (i) { const yp = this.p2y(lv[i - 1][1]); ctx.fillStyle = alpha(col, 0.07); ctx.fillRect(xa, Math.min(y, yp), xb - xa, Math.abs(y - yp)); }
          ctx.strokeStyle = col; ctx.lineWidth = 1; line(xa, y, xb, y);
          ctx.fillStyle = col; ctx.fillText(`${r} (${this.tc.px(p)})`, xa + 2, y - 3);
        });
        ctx.strokeStyle = alpha(d.color, 0.6); ctx.setLineDash([4, 4]); line(x1, y1, x2, y2); if (P[2]) line(x2, y2, P[2][0], P[2][1]); ctx.setLineDash([]);
        break;
      }
      case "text": this._label(ctx, d.text || "", x1, y1, alpha("#131722", 0.85), d.color); break;
      case "range": case "daterange": {
        const dp = d.pts[1].p - d.pts[0].p, pctv = dp / d.pts[0].p * 100, bars = Math.round((d.pts[1].t - d.pts[0].t) / this._step());
        const up = dp >= 0, col = up ? "#2962ff" : "#f23645";
        ctx.fillStyle = alpha(col, 0.15); ctx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
        ctx.strokeStyle = col; ctx.lineWidth = 1; line((x1 + x2) / 2, y1, (x1 + x2) / 2, y2); if (d.type === "daterange") line(x1, (y1 + y2) / 2, x2, (y1 + y2) / 2);
        const secs = Math.abs(d.pts[1].t - d.pts[0].t), dur = secs >= 86400 ? `${(secs / 86400).toFixed(1)}일` : `${(secs / 3600).toFixed(1)}시간`;
        this._label(ctx, `${up ? "+" : ""}${this.tc.px(dp)} (${up ? "+" : ""}${pctv.toFixed(2)}%) · ${bars}봉${d.type === "daterange" ? ` · ${dur}` : ""}`, (x1 + x2) / 2, Math.max(y1, y2) + 20, col, "#fff", "center");
        break;
      }
      case "long": case "short": {
        const [e, s, t, r] = d.pts, xe = this.t2x(e.t), xr = this.t2x(r?.t ?? e.t), ye = this.p2y(e.p), ys = this.p2y(s.p), yt = this.p2y(t.p);
        const w = (xr ?? xe + 120) - xe;
        ctx.fillStyle = "rgba(242,54,69,.18)"; ctx.fillRect(xe, Math.min(ye, ys), w, Math.abs(ys - ye));
        ctx.fillStyle = "rgba(8,153,129,.18)"; ctx.fillRect(xe, Math.min(ye, yt), w, Math.abs(yt - ye));
        ctx.strokeStyle = "#787b86"; ctx.lineWidth = 1; line(xe, ye, xe + w, ye);
        const risk = Math.abs(e.p - s.p), rr = risk ? Math.abs(t.p - e.p) / risk : 0, sgn = d.type === "long" ? 1 : -1;
        const tp = sgn * (t.p / e.p - 1) * 100, sp = sgn * (s.p / e.p - 1) * 100;
        this._label(ctx, `목표 ${this.tc.px(t.p)} (${tp >= 0 ? "+" : ""}${tp.toFixed(2)}%) · RR ${rr.toFixed(2)}`, xe + w / 2, yt + (sgn > 0 ? -4 : 18), "#089981", "#fff", "center");
        this._label(ctx, `손절 ${this.tc.px(s.p)} (${sp.toFixed(2)}%)`, xe + w / 2, ys + (sgn > 0 ? 18 : -4), "#f23645", "#fff", "center");
        this._label(ctx, `${d.type === "long" ? "롱" : "숏"} 진입 ${this.tc.px(e.p)}`, xe + 2, ye - 3, "#2a2e39");
        if (sel) [[xe, ye], [xe, ys], [xe, yt], [xe + w, ye]].forEach(([ax, ay]) => this._handle(ctx, ax, ay));
        return;
      }
      case "brush": {
        ctx.beginPath(); P.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke(); return;
      }
      default: break;
    }
    if (sel || d.id === "_temp") P.forEach(([ax, ay]) => ax != null && this._handle(ctx, d.type === "hline" ? W / 2 : ax, ay));
  }
  _handle(ctx, x, y) {
    if (x == null || y == null) return;
    ctx.setLineDash([]); ctx.fillStyle = "#131722"; ctx.strokeStyle = "#2962ff"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(x, y, 4.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
  }
}
export { COLORS };

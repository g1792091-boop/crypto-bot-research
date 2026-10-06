// 차트 그리기 + 이 가격에 알림 (conv-b, owners 10/06: "차트에 선 긋고, 그 가격에 알림 걸고 싶다"), on the 터미널 chart and
// the 차트 screen's chart (the same chart deck, core/chartfx.js):
//   그리기    a '그리기' toggle in the chart head opens a small tool column at the pane's left edge: 선택 (pick, move,
//             reshape by the end handles), 가로선, 추세선 (drag, or click twice), 네모 (drag, or click twice), 글 (a short
//             note at a point), 지우기 (the picked one; Delete / Backspace too) and 전부 지우기 (asks once more). Drawings
//             are saved per coin + timeframe on this device ("draw-<COIN>-<tf>", dom.js `local`, try/catch inside), at
//             most MAX_SHAPES each; drawn in one colour (--draw, both skins: a hue nothing else on the chart uses) by a series primitive above the candles.
//   알림      a right click on the chart (a long press on a phone or tablet) opens a small menu: '이 가격에 알림 <price>'
//             makes a price alert through the EXISTING route the 가격 알림 pane uses (POST /api/price-alerts {symbol,
//             price}: the server sets above / below from the current price, paperbot-tgtrades rings Telegram loudly
//             once; nothing about how alerts are sent changes here), '가로선 긋기' at that price, '이 그림 지우기' on a
//             drawing. The armed alerts of the coin are the deck's '가격 알림 선' lines (the caller loads them).
// HONESTY: drawings are the viewer's own marks (never a signal, never sent anywhere); an alert is made only by an
// explicit menu choice, and the server's own Korean answer is shown (success or error). Paper only: no orders.
import {h, s, fmt, tok, priceDec, local} from "../core/pb.js";

export const MAX_SHAPES = 40;
export const KINDS = ["h", "line", "rect", "text"];
const HIT = 7, HANDLE = 5, LONG_MS = 550, MOVE_TOL = 10;
const TOOLS = [
  {id: null, ko: "선택·옮기기", key: "선택"},
  {id: "h", ko: "가로선 (한 번 누르기)", key: "가로선"},
  {id: "line", ko: "추세선 (끌기, 또는 두 번 누르기)", key: "추세선"},
  {id: "rect", ko: "네모 (끌기, 또는 두 번 누르기)", key: "네모"},
  {id: "text", ko: "글 (누른 곳에 짧은 메모)", key: "글"},
];

// ---------------------------------------------------------------- pure helpers (node-tested)
const num = (x) => typeof x === "number" && Number.isFinite(x);
const pt = (o) => o && typeof o === "object" && num(o.x) && num(o.p) ? {x: Math.round(o.x), p: o.p} : null;
/** The stored drawings, cleaned: known kinds with finite numbers, short texts, at most MAX_SHAPES (the newest kept). */
export function readShapes(raw) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  for (const x of raw) {
    if (!x || typeof x !== "object" || !KINDS.includes(x.t)) continue;
    const id = typeof x.id === "string" && /^[a-z0-9]{1,16}$/.test(x.id) ? x.id : null;
    if (!id) continue;
    if (x.t === "h") { if (num(x.p)) out.push({id, t: "h", p: x.p}); continue; }
    const a = pt(x.a);
    if (!a) continue;
    if (x.t === "text") {
      const txt = typeof x.s === "string" ? x.s.trim().slice(0, 60) : "";
      if (txt) out.push({id, t: "text", a, s: txt});
      continue;
    }
    const b = pt(x.b);
    if (b) out.push({id, t: x.t, a, b});
  }
  return out.slice(-MAX_SHAPES);
}
export const shapeKey = (sym, tf) => `draw-${sym}-${tf}`;

/** A float bar index (lightweight-charts logical) for a time in seconds over bars [{time}] (step: the bar length);
 *  past either end it goes on by whole bars. Null without bars. */
export function logicalOf(bars, t, step) {
  const n = (bars || []).length;
  if (!n) return null;
  const t0 = bars[0].time, tl = bars[n - 1].time;
  if (t <= t0) return (t - t0) / step;
  if (t >= tl) return n - 1 + (t - tl) / step;
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (bars[m].time <= t) lo = m; else hi = m; }
  return lo + (t - bars[lo].time) / (bars[hi].time - bars[lo].time);
}
/** The time (s) of a float bar index (the inverse of logicalOf). */
export function timeOf(bars, l, step) {
  const n = (bars || []).length;
  if (!n) return null;
  if (l <= 0) return bars[0].time + l * step;
  if (l >= n - 1) return bars[n - 1].time + (l - (n - 1)) * step;
  const i = Math.floor(l), f = l - i;
  return bars[i].time + f * (bars[i + 1].time - bars[i].time);
}
/** Distance from (px, py) to the segment (x1, y1)-(x2, y2). */
export function segDist(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1, L = dx * dx + dy * dy;
  const u = L ? Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / L)) : 0;
  return Math.hypot(px - (x1 + u * dx), py - (y1 + u * dy));
}
/** What a pointer at (x, y) touches of one drawing in screen coordinates g ({a:{x,y}, b:{x,y}} or {y} or a text box):
 *  "a" / "b" (an end handle), "body", or null. */
export function hitTest(sh, g, x, y) {
  if (!g) return null;
  if (sh.t === "h") return Math.abs(y - g.y) <= HIT ? "body" : null;
  if (sh.t === "text") return x >= g.x - 4 && x <= g.x + g.w + 4 && y >= g.y - g.h - 4 && y <= g.y + 4 ? "body" : null;
  if (Math.hypot(x - g.a.x, y - g.a.y) <= HIT + 2) return "a";
  if (Math.hypot(x - g.b.x, y - g.b.y) <= HIT + 2) return "b";
  if (sh.t === "line") return segDist(x, y, g.a.x, g.a.y, g.b.x, g.b.y) <= HIT ? "body" : null;
  const x0 = Math.min(g.a.x, g.b.x), x1 = Math.max(g.a.x, g.b.x), y0 = Math.min(g.a.y, g.b.y), y1 = Math.max(g.a.y, g.b.y);
  return x >= x0 - HIT && x <= x1 + HIT && y >= y0 - HIT && y <= y1 + HIT ? "body" : null;
}
/** The price rounded to the chart's own decimals (priceDec). */
export const roundPrice = (p) => { const d = priceDec(p); return Math.round(p * 10 ** d) / 10 ** d; };
const newId = () => Math.random().toString(36).slice(2, 10) || "x";

// ---------------------------------------------------------------- the icons (16 x 16, currentColor)
const ICON = {
  null: () => [s("path", {d: "M3 2 L3 13 L6 10 L8 14 L10 13 L8 9 L12 9 Z", fill: "currentColor"})],
  h: () => [s("rect", {x: 1, y: 7, width: 14, height: 2, fill: "currentColor"})],
  line: () => [s("path", {d: "M2 13 L14 3", stroke: "currentColor", "stroke-width": 2, fill: "none"}), s("rect", {x: 1, y: 12, width: 3, height: 3, fill: "currentColor"}),
    s("rect", {x: 12, y: 1, width: 3, height: 3, fill: "currentColor"})],
  rect: () => [s("rect", {x: 2, y: 4, width: 12, height: 8, stroke: "currentColor", "stroke-width": 2, fill: "none"})],
  text: () => [s("path", {d: "M3 3 H13 M8 3 V14", stroke: "currentColor", "stroke-width": 2, fill: "none"})],
  del: () => [s("path", {d: "M3 4 H13 M6 4 V2 H10 V4 M4 4 L5 14 H11 L12 4", stroke: "currentColor", "stroke-width": 1.6, fill: "none"})],
  all: () => [s("path", {d: "M2 4 H14 M5 4 L6 14 H10 L11 4 M3 2 L13 12", stroke: "currentColor", "stroke-width": 1.6, fill: "none"})],
};
const icon = (k) => s("svg", {viewBox: "0 0 16 16", width: 16, height: 16, "aria-hidden": "true"}, (ICON[k] || ICON.null)());

/**
 * drawTools({ctx, chart, series, wrap, box, deck, sym(), tf(), step(), onAlertAdded}) -> {toggle, setKey(), redraw()}
 *   toggle: the '그리기' head button (put it with the deck's head controls); setKey(): after a coin / timeframe change
 *   (loads that pair's drawings); redraw(): after new candles (the deck's data).
 */
export function drawTools(o) {
  const {ctx, chart, series, wrap, box, deck} = o;
  const st = {shapes: [], key: null, sel: null, mode: null, draft: null, drag: null, menu: null, api: null, longT: 0, menuAt: 0, armDel: 0};
  const col = () => ({line: tok("--draw"), ink: tok("--ink"), bg: tok("--pill-bg"), font: tok("--f-body"), fs: parseFloat(tok("--t-xs")) || 13, hi: tok("--accent")});
  let C = col();

  // ---------------------------------------------------------------- coordinates
  const bars = () => (deck && deck.data ? deck.data() : []);
  const pane = () => {
    let sw = 0, th = 0;
    try { sw = chart.priceScale("right").width(); th = chart.timeScale().height(); } catch (e) { /* mid-layout */ }
    return {w: box.clientWidth - sw, h: box.clientHeight - th};
  };
  const xOf = (t) => { const l = logicalOf(bars(), t, o.step()); return l == null ? null : chart.timeScale().logicalToCoordinate(l); };
  const yOf = (p) => series.priceToCoordinate(p);
  const at = (x, y) => {
    const l = chart.timeScale().coordinateToLogical(x), p = series.coordinateToPrice(y);
    const t = l == null ? null : timeOf(bars(), l, o.step());
    return t == null || p == null ? null : {x: Math.round(t), p};
  };
  /** Screen geometry of one drawing (null when it cannot be placed now). */
  function geo(sh, g2d) {
    if (sh.t === "h") { const y = yOf(sh.p); return y == null ? null : {y}; }
    const ax = xOf(sh.a.x), ay = yOf(sh.a.p);
    if (ax == null || ay == null) return null;
    if (sh.t === "text") {
      let w = sh.s.length * C.fs * 0.62;
      if (g2d) { g2d.font = `600 ${C.fs}px ${C.font}`; w = g2d.measureText(sh.s).width; }
      return {x: ax, y: ay, w: w + 12, h: C.fs + 8};
    }
    const bx = xOf(sh.b.x), by = yOf(sh.b.p);
    return bx == null || by == null ? null : {a: {x: ax, y: ay}, b: {x: bx, y: by}};
  }

  // ---------------------------------------------------------------- the primitive (above the candles)
  const measure = document.createElement("canvas").getContext("2d");
  const renderer = {
    draw(target) {
      target.useBitmapCoordinateSpace(({context: c, horizontalPixelRatio: hr, verticalPixelRatio: vr, bitmapSize}) => {
        const all = st.draft ? [...st.shapes, st.draft] : st.shapes;
        if (!all.length) return;
        c.save();
        for (const sh of all) {
          const g = geo(sh, measure);
          if (!g) continue;
          const on = st.sel === sh.id || sh === st.draft;
          c.strokeStyle = C.line; c.fillStyle = C.line; c.lineWidth = Math.max(1, Math.round((on ? 2 : 1.4) * hr));
          c.setLineDash([]);
          if (sh.t === "h") {
            const y = Math.round(g.y * vr) + 0.5;
            c.beginPath(); c.moveTo(0, y); c.lineTo(bitmapSize.width, y); c.stroke();
          } else if (sh.t === "line") {
            c.beginPath(); c.moveTo(g.a.x * hr, g.a.y * vr); c.lineTo(g.b.x * hr, g.b.y * vr); c.stroke();
          } else if (sh.t === "rect") {
            const x0 = Math.min(g.a.x, g.b.x) * hr, y0 = Math.min(g.a.y, g.b.y) * vr, w = Math.abs(g.b.x - g.a.x) * hr, hh = Math.abs(g.b.y - g.a.y) * vr;
            c.globalAlpha = 0.1; c.fillRect(x0, y0, w, hh); c.globalAlpha = 1; c.strokeRect(x0, y0, w, hh);
          } else if (sh.t === "text") {
            c.font = `600 ${Math.round(C.fs * vr)}px ${C.font}`;
            c.fillStyle = C.bg; c.fillRect(g.x * hr, (g.y - g.h) * vr, g.w * hr, g.h * vr);
            c.strokeRect(g.x * hr, (g.y - g.h) * vr, g.w * hr, g.h * vr);
            c.fillStyle = C.ink; c.textBaseline = "middle"; c.fillText(sh.s, (g.x + 6) * hr, (g.y - g.h / 2) * vr);
          }
          if (on && sh.t !== "h" && sh.t !== "text") {
            for (const q of [g.a, g.b]) {
              c.fillStyle = C.ink; c.fillRect((q.x - HANDLE) * hr, (q.y - HANDLE) * vr, 2 * HANDLE * hr, 2 * HANDLE * vr);
              c.strokeRect((q.x - HANDLE) * hr, (q.y - HANDLE) * vr, 2 * HANDLE * hr, 2 * HANDLE * vr);
            }
          }
        }
        c.restore();
      });
    },
  };
  series.attachPrimitive({
    attached(p) { st.api = p; }, detached() { st.api = null; },
    paneViews: () => [{zOrder: () => "top", renderer: () => renderer}],
    updateAllViews() {},
  });
  const redraw = () => { if (st.api) st.api.requestUpdate(); };

  // ---------------------------------------------------------------- storage
  const save = () => { if (st.key) local.set(st.key, st.shapes.slice(-MAX_SHAPES)); };
  function setKey() {
    st.key = shapeKey(o.sym(), o.tf());
    st.shapes = readShapes(local.get(st.key, []));
    st.sel = null; st.draft = null; st.drag = null;
    closeMenu(); setMode(null); paintTools(); redraw();
  }
  function add(sh) {
    st.shapes = [...st.shapes, sh].slice(-MAX_SHAPES);
    st.sel = sh.id; save(); paintTools(); redraw();
  }
  function remove(id) {
    st.shapes = st.shapes.filter((x) => x.id !== id);
    if (st.sel === id) st.sel = null;
    save(); paintTools(); redraw();
  }

  // ---------------------------------------------------------------- the head toggle + the tool column
  const toolBtns = new Map();
  const delBtn = h("button", {type: "button", class: "drw-b", title: "고른 그림 지우기 (Delete)", "aria-label": "고른 그림 지우기", onclick: () => { if (st.sel) remove(st.sel); }}, icon("del"));
  const allBtn = h("button", {type: "button", class: "drw-b", title: "이 코인·봉의 그림 전부 지우기", "aria-label": "그림 전부 지우기", onclick: () => {
    if (!st.shapes.length) return;
    if (Date.now() - st.armDel > 4000) { st.armDel = Date.now(); allBtn.classList.add("arm"); allBtn.title = "한 번 더 누르면 전부 지웁니다";
      ctx.timeout(() => { allBtn.classList.remove("arm"); allBtn.title = "이 코인·봉의 그림 전부 지우기"; }, 4000); return; }
    st.armDel = 0; allBtn.classList.remove("arm"); st.shapes = []; st.sel = null; save(); paintTools(); redraw();
  }}, icon("all"));
  const count = h("span", {class: "drw-n num", "aria-live": "polite"});
  const tools = h("div", {class: "drw-tools", role: "toolbar", "aria-label": "그리기 도구", hidden: true},
    TOOLS.map((x) => {
      const b = h("button", {type: "button", class: "drw-b", title: x.ko, "aria-label": x.ko, "aria-pressed": "false", onclick: () => setMode(st.mode === x.id ? null : x.id)}, icon(String(x.id)));
      toolBtns.set(x.id, b);
      return b;
    }), h("i", {class: "drw-sep", "aria-hidden": "true"}), delBtn, allBtn, count);
  wrap.append(tools);
  const toggle = h("button", {type: "button", class: "drw-toggle", "aria-pressed": "false",
    title: "그리기: 가로선·추세선·네모·글 (이 기기에 코인·봉마다 저장) · 차트에서 오른쪽 클릭(휴대폰은 길게 누르기) = 이 가격에 알림",
    onclick: () => openTools(tools.hidden)}, "그리기");
  function openTools(on) {
    tools.hidden = !on;
    toggle.setAttribute("aria-pressed", String(on));
    wrap.classList.toggle("drw-on", on);
    local.set("draw-open", on);
    if (!on) setMode(null);
    if (deck && deck.place) deck.place();
  }
  function paintTools() {
    for (const [id, b] of toolBtns) b.setAttribute("aria-pressed", String(st.mode === id));
    delBtn.disabled = !st.sel;
    allBtn.disabled = !st.shapes.length;
    count.textContent = st.shapes.length ? String(st.shapes.length) : "";
    count.title = `이 코인·봉 그림 ${st.shapes.length}개 (최대 ${MAX_SHAPES})`;
  }
  function setMode(m) {
    st.mode = m || null;
    st.draft = null;
    // while a tool draws, the chart does not pan or zoom under the pointer
    try { chart.applyOptions({handleScroll: !st.mode, handleScale: !st.mode}); } catch (e) { /* older */ }
    wrap.classList.toggle("drw-drawing", !!st.mode);
    paintTools(); redraw();
  }

  // ---------------------------------------------------------------- the right-click / long-press menu
  function closeMenu() { if (st.menu) { st.menu.remove(); st.menu = null; } }
  function openMenu(x, y) {
    closeMenu();
    const P = pane();
    if (x < 0 || y < 0 || x > P.w || y > P.h) return;
    const p0 = series.coordinateToPrice(y);
    if (p0 == null || !(p0 > 0)) return;
    const price = roundPrice(p0), sym = o.sym();
    const last = bars().length ? bars()[bars().length - 1].close : null;
    const dir = last == null ? "" : price > last ? " · 지금보다 위 (오르면 울림)" : " · 지금보다 아래 (내리면 울림)";
    const hit = topHit(x, y);
    const item = (text, fn, cls) => h("button", {type: "button", role: "menuitem", class: ["drw-mi", cls || ""], onclick: (e) => { e.stopPropagation(); closeMenu(); fn(); }}, text);
    st.menu = h("div", {class: "drw-menu", role: "menu", "aria-label": "차트 메뉴"},
      h("p", {class: "drw-mh num"}, `${fmt.coin(sym)} ${fmt.price(price)}`),
      item(["이 가격에 알림", h("small", null, `텔레그램 소리 알림${dir}`)], () => makeAlert(sym, price), "alert"),
      item("여기에 가로선 긋기", () => add({id: newId(), t: "h", p: price})),
      hit ? item("이 그림 지우기", () => remove(hit.id), "bad") : null,
      item("닫기", () => {}));
    wrap.append(st.menu);
    st.menuAt = Date.now();
    const mw = st.menu.offsetWidth || 220, mh = st.menu.offsetHeight || 150;
    st.menu.style.left = `${Math.round(Math.max(4, Math.min(x + box.offsetLeft, wrap.clientWidth - mw - 4)))}px`;
    st.menu.style.top = `${Math.round(Math.max(4, Math.min(y + box.offsetTop, wrap.clientHeight - mh - 4)))}px`;
    const f = st.menu.querySelector(".drw-mi");
    if (f) f.focus({preventScroll: true});
  }
  async function makeAlert(sym, price) {
    try {
      const r = await ctx.post("/api/price-alerts", {symbol: sym, price});
      ctx.toast(`${fmt.coin(sym)} ${fmt.price(price)} ${r && r.direction === "above" ? "위로 오르면" : "아래로 내리면"} 텔레그램으로 알립니다 (한 번 울리면 꺼짐)`);
      if (o.onAlertAdded) o.onAlertAdded();
    } catch (e) {
      if (!(e && e.name === "AbortError")) ctx.toast((e && e.detail) || "알림을 저장하지 못했습니다. 잠시 뒤 다시 해 주세요.");
    }
  }

  // ---------------------------------------------------------------- pointer handling
  const local2 = (e) => { const r = box.getBoundingClientRect(); return {x: e.clientX - r.left, y: e.clientY - r.top}; };
  function topHit(x, y) {
    for (let i = st.shapes.length - 1; i >= 0; i--) {
      const sh = st.shapes[i], part = hitTest(sh, geo(sh, measure), x, y);
      if (part) return {id: sh.id, part, sh};
    }
    return null;
  }
  let block = false;                       // this gesture belongs to the drawing: the chart's own handlers stay out of it
  const swallow = (e) => { if (block) { e.stopPropagation(); } };
  wrap.addEventListener("mousedown", swallow, true);
  wrap.addEventListener("touchstart", swallow, {capture: true, passive: true});
  wrap.addEventListener("pointerdown", (e) => {
    block = false;
    if (st.menu && !st.menu.contains(e.target)) closeMenu();
    if (e.target.closest && e.target.closest(".drw-tools, .drw-menu, .drw-input, .cfx-pill, .cfx-menu, button, input, select")) return;
    const {x, y} = local2(e), P = pane();
    if (x < 0 || y < 0 || x > P.w || y > P.h) return;
    if (e.pointerType === "touch" && !st.mode) {
      clearTimeout(st.longT);
      const sx = e.clientX, sy = e.clientY;
      st.longT = setTimeout(() => { st.longT = 0; openMenu(x, y); }, LONG_MS);
      const cancel = (ev) => { if (ev.type !== "pointermove" || Math.hypot(ev.clientX - sx, ev.clientY - sy) > MOVE_TOL) { clearTimeout(st.longT); off(); } };
      const off = () => { for (const k of ["pointermove", "pointerup", "pointercancel"]) window.removeEventListener(k, cancel); };
      for (const k of ["pointermove", "pointerup", "pointercancel"]) window.addEventListener(k, cancel);
    }
    if (e.button !== 0) return;
    const q = at(x, y);
    if (st.mode) {
      if (!q) return;
      block = true; e.preventDefault();
      if (st.mode === "h") { add({id: newId(), t: "h", p: q.p}); setMode(null); return; }
      if (st.mode === "text") { if (!wrap.querySelector(".drw-input")) askText(x, y, q); return; }
      if (st.draft && st.draft.wait) { st.draft.b = q; finishDraft(); return; }
      st.draft = {id: newId(), t: st.mode, a: q, b: q, sx: x, sy: y};
      startDrag("draft");
      return;
    }
    const hit = topHit(x, y);
    if (!hit) { if (st.sel) { st.sel = null; paintTools(); redraw(); } return; }
    block = true; e.preventDefault();
    st.sel = hit.id; paintTools(); redraw();
    st.drag = {id: hit.id, part: hit.part, orig: JSON.parse(JSON.stringify(hit.sh)), from: q, l0: chart.timeScale().coordinateToLogical(x), y0: y, moved: false};
    startDrag("shape");
  }, true);

  function startDrag(kind) {
    try { chart.applyOptions({handleScroll: false, handleScale: false}); } catch (e) { /* older */ }
    const move = (e) => {
      const {x, y} = local2(e);
      if (kind === "draft" && st.draft) {
        const q = at(x, y);
        if (q) st.draft.b = q;
        redraw();
      } else if (kind === "shape" && st.drag) {
        dragShape(x, y);
      }
    };
    const up = (e) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      block = false;
      if (kind === "draft" && st.draft) {
        const {x, y} = local2(e);
        if (Math.hypot(x - st.draft.sx, y - st.draft.sy) < 5) st.draft.wait = true;      // a click: the second click ends it
        else finishDraft();
      } else if (kind === "shape" && st.drag) {
        if (st.drag.moved) save();
        st.drag = null;
      }
      try { chart.applyOptions({handleScroll: !st.mode, handleScale: !st.mode}); } catch (e2) { /* older */ }
      redraw();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  }
  function finishDraft() {
    const d = st.draft;
    st.draft = null;
    if (d && (d.a.x !== d.b.x || d.a.p !== d.b.p)) add({id: d.id, t: d.t, a: d.a, b: d.b});
    setMode(null);
  }
  function dragShape(x, y) {
    const d = st.drag, sh = st.shapes.find((z) => z.id === d.id);
    if (!sh) return;
    const p1 = series.coordinateToPrice(y), l1 = chart.timeScale().coordinateToLogical(x);
    if (p1 == null || l1 == null || !d.from) return;
    const dp = p1 - d.from.p, dl = l1 - d.l0;
    const shift = (q) => { const l = logicalOf(bars(), q.x, o.step()); const t = l == null ? q.x : timeOf(bars(), l + dl, o.step()); return {x: Math.round(t), p: q.p + dp}; };
    const og = d.orig;
    if (sh.t === "h") sh.p = og.p + dp;
    else if (d.part === "a") sh.a = at(x, y) || sh.a;
    else if (d.part === "b") sh.b = at(x, y) || sh.b;
    else { sh.a = shift(og.a); if (og.b) sh.b = shift(og.b); }
    d.moved = true;
    redraw();
  }

  // the note box of the 글 tool: Enter keeps it, Esc drops it
  function askText(x, y, q) {
    const inp = h("input", {class: "drw-input", type: "text", maxlength: "60", placeholder: "메모 (Enter)", "aria-label": "그림 메모"});
    inp.style.left = `${Math.round(Math.min(x + box.offsetLeft, wrap.clientWidth - 200))}px`;
    inp.style.top = `${Math.round(Math.max(4, y + box.offsetTop - 34))}px`;
    let done = false;
    const end = (keep) => {
      if (done) return;
      done = true;
      const txt = inp.value.trim().slice(0, 60);
      inp.remove();
      if (keep && txt) add({id: newId(), t: "text", a: q, s: txt});
      setMode(null);
    };
    inp.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); end(true); }
      else if (e.key === "Escape") { e.preventDefault(); end(false); }
    });
    inp.addEventListener("blur", () => end(true));
    wrap.append(inp);
    inp.focus();
  }

  wrap.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    if (Date.now() - st.menuAt < 800 && st.menu) return;          // the long press already opened it
    const {x, y} = local2(e);
    openMenu(x, y);
  });
  // a line / box finished by a second click follows the pointer until then
  wrap.addEventListener("pointermove", (e) => {
    if (!st.draft || !st.draft.wait) return;
    const {x, y} = local2(e), q = at(x, y);
    if (q) { st.draft.b = q; redraw(); }
  });
  // a click outside this chart closes its menu and lets go of the picked drawing (Delete then never reaches it)
  ctx.listen(document, "pointerdown", (e) => {
    if (wrap.contains(e.target)) return;
    if (st.menu) closeMenu();
    if (st.sel) { st.sel = null; paintTools(); redraw(); }
  });
  ctx.listen(document, "keydown", (e) => {
    const el = document.activeElement;
    if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
    if (e.key === "Escape") {
      if (st.menu) { closeMenu(); e.preventDefault(); return; }
      if (st.mode || st.draft) { setMode(null); e.preventDefault(); return; }
      if (st.sel) { st.sel = null; paintTools(); redraw(); }
      return;
    }
    if ((e.key === "Delete" || e.key === "Backspace") && st.sel && !e.ctrlKey && !e.metaKey) { e.preventDefault(); remove(st.sel); }
  });
  ctx.track(() => { clearTimeout(st.longT); closeMenu(); });

  if (local.get("draw-open", false) === true) openTools(true);
  setKey();
  return {
    toggle,
    setKey,
    /** New candles or a new skin: the drawings follow the bars. */
    redraw() { C = col(); redraw(); },
  };
}

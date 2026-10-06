// The chart deck (owners 10/06: "선이 너무 크고 투박하다, 누르면 숨기게, 차트가 비어 보인다, 간지나게"): one helper the
// terminal chart and the 차트 screen share on top of the vendored lightweight-charts (v4.2 series primitives).
//   glow       AI skin only: candles and wicks get a soft neon glow in their up / down colours, the forming candle a
//              little brighter, the last price a glowing line, our entry / exit marks a halo; a faint depth gradient.
//              Drawn under the candles (primitive zOrder "bottom"), so the candles and every text stay crisp.
//   ambient    AI skin only, like the reference terminal: the pane is split at the equilibrium of the current dealing
//              range (core/smc.js splitOf; fallback the middle of the visible high / low): the Premium part above is
//              washed red (strongest at the top edge), the Discount part below sky blue (strongest at the bottom edge),
//              a soft seam between, faint 'Premium' / 'Discount' words at the right. The split follows the price scale
//              (pan / zoom) and moves when the dealing range really changes (a new closed bar).
//   flash      AI skin only: a real market event of this coin (a big taker trade from the server relay, a market
//              liquidation, our own bot's fill) washes the pane once (core/flash.js scheduler: 0.2 s in, a 0.6 s hold
//              or 1.5 s for a 고래 / a large liquidation, 0.4 s out; '번쩍임 자주 / 보통 / 끄기' per device). Reduced
//              motion: no flash.
//   lines      our position / stop / support-resistance / alert lines: 1 px, low alpha (a faint glow in AI), a compact
//              pill at the LEFT edge inside the pane, only a small tag on the right axis; never in the autoscale (the
//              candles keep filling the pane); a line off the price range becomes a small ▲ / ▼ edge marker.
//              Nearby pills are offset, then merged ("+N"), never overlapping. Clicking a pill (or its ×) hides it.
//   menu       '선' in the chart header: the line groups on / off, 모두 보기 / 모두 숨기기, the hidden lines back.
//              Remembered per device (dom.js local, try/catch inside).
//   smc        프리미엄 지표: core/smc.js on the closed candles shown, drawn by core/smcdraw.js (an indicator, labelled).
//   volume     translucent up / down volume bars along the bottom (an overlay price scale of their own).
// HONESTY: every motion answers a real change (a new price, a real event); nothing animates on a timer. Colours are
// tokens (tokens.css), font sizes the --t-* tokens.
import {h, local} from "./dom.js";
import {tok} from "./lwc.js";
import {price as fmtPrice} from "./fmt.js";
import {reduced, visible} from "./motion.js";
import {flashScheduler, ENVELOPE, FLASH_MODES, DEFAULT_FLASH, modeOf} from "./flash.js";
import {smcAll, splitOf, zoneOf} from "./smc.js";
import {smcPrimitive} from "./smcdraw.js";
import {onPref} from "./prefs.js";

export const GROUP_KO = {pos: "포지션 선", risk: "손절·잠금", sr: "지지·저항", smc: "프리미엄 지표", ev: "경제지표", vol: "거래량", al: "가격 알림 선"};
export const AMBIENT_TIP = "위쪽 빨간 빛 = Premium (지금 범위의 중간값 위) / 아래쪽 하늘색 = Discount (중간값 아래)";
export const FLASH_TIP = "하늘색 번쩍 = 큰 매수·숏 청산, 빨간 번쩍 = 큰 매도·롱 청산 (바이낸스 실제 체결)";
export const SMC_NOTE = "프리미엄 지표: 화면의 캔들로 계산한 참고선 (스윙·구조·OB·FVG·OTE) · 매매 신호 아님";
const SMC_KEY = "프리미엄 지표 · 계산한 참고선 · 신호 아님";
/** The AI skin (the default) has the light; 클래식 stays plain. */
export const isAi = () => typeof document !== "undefined" && document.documentElement.dataset.skin !== "classic";
const narrow = () => typeof matchMedia === "function" && matchMedia("(max-width: 599px)").matches;
const TONES = ["up", "down", "flat", "accent", "warn"];
const PILL_H = 20, PILL_GAP = 2, EDGE_MAX = 3, TOP_GAP = 26, FLASH_KEY = "chart-flash";

function colours() {
  const c = {};
  for (const [k, n] of [["up", "--up"], ["down", "--down"], ["upGlow", "--up-glow"], ["downGlow", "--down-glow"], ["accent", "--accent"],
    ["accentGlow", "--accent-glow"], ["warn", "--warn"], ["flat", "--muted"], ["ink", "--ink-2"], ["axisInk", "--accent-ink"],
    ["volUp", "--vol-up"], ["volDown", "--vol-down"], ["font", "--f-term"], ["fs", "--t-2xs"], ["bg", "--bg"],
    ["ob", "--smc-ob"], ["fvg", "--smc-fvg"], ["liq", "--smc-liq"], ["bos", "--smc-bos"], ["choch", "--smc-choch"], ["trend", "--smc-trend"],
    ["prem", "--smc-prem"], ["disc", "--smc-disc"], ["ote", "--smc-ote"]]) c[k] = tok(n);
  c.fs = parseFloat(c.fs) || 12;
  return c;
}

/**
 * glowPrimitive({chart, series, data, marks, idx, col, ai, onUpdate}) -> a series primitive (zOrder "bottom"): the
 * candles' neon glow in their up / down colours, the forming candle brighter with a faint column of light, a glowing
 * hairline at the last price, a halo on our entry / exit marks. Draws nothing unless ai() (the AI skin).
 *   data() -> the bars on the series (logical index = array index); marks() / idx(time) -> the series markers
 */
export function glowPrimitive(o) {
  const {chart, series} = o;
const gv = {bars: [], last: null, w: 2, py: null, halos: []};
const smalls = new Map();                   // the reused small canvases of the candle glow, by scale
const small = (S, w, hh) => {
  let cv = smalls.get(S);
  if (!cv) { cv = document.createElement("canvas"); smalls.set(S, cv); }
  if (cv.width !== w) cv.width = w;
  if (cv.height !== hh) cv.height = hh;
  return cv;
};
const glowR = {
  draw() {},
  drawBackground(target) {
    if (!o.ai() || !gv.bars.length) return;
    target.useBitmapCoordinateSpace(({context: c, horizontalPixelRatio: hr, verticalPixelRatio: vr, bitmapSize}) => {
      const col = o.col();
      const bw = Math.max(1, Math.round(gv.w * hr));
      c.save();
      // the candles' glow: the bodies and wicks drawn small (1/4 and 1/8 of the size) and stretched back with
      // smoothing, a soft light in their own colours for the cost of two image copies (no per-frame blur filter)
      c.imageSmoothingEnabled = true;
      try { c.imageSmoothingQuality = "high"; } catch (e) { /* older browsers: default smoothing */ }
      for (const [S, a] of (o.lite ? LITE_PASSES : GLOW_PASSES)) {
        const ow = Math.max(1, Math.ceil(bitmapSize.width / S)), oh = Math.max(1, Math.ceil(bitmapSize.height / S));
        const off = small(S, ow, oh), o2 = off.getContext("2d");
        o2.clearRect(0, 0, ow, oh);
        const sw = Math.max(1, bw / S + 1), ww = Math.max(0.8, (2 * hr) / S);
        for (const tone of ["up", "down"]) {
          o2.fillStyle = col[tone];
          o2.beginPath();
          for (const b of gv.bars) {
            if (b.up !== (tone === "up")) continue;
            const X = (b.x * hr) / S;
            o2.rect(X - sw / 2, (b.t * vr) / S, sw, Math.max(0.8, ((b.b - b.t) * vr) / S));
            o2.rect(X - ww / 2, (b.hi * vr) / S, ww, Math.max(0.8, ((b.lo - b.hi) * vr) / S));
          }
          o2.fill();
        }
        c.globalAlpha = a;
        c.drawImage(off, 0, 0, ow, oh, 0, 0, ow * S, oh * S);
      }
      // the forming candle: a little brighter, a faint column of light behind it
      const f = gv.last;
      if (f) {
        const X = Math.round(f.x * hr), cw = Math.max(6 * hr, bw * 4);
        const g = c.createLinearGradient(0, 0, 0, bitmapSize.height);
        g.addColorStop(0, "transparent"); g.addColorStop(0.5, f.up ? col.upGlow : col.downGlow); g.addColorStop(1, "transparent");
        c.shadowBlur = 0; c.globalAlpha = 0.07; c.fillStyle = g;
        c.fillRect(X - cw / 2, 0, cw, bitmapSize.height);
        c.shadowColor = f.up ? col.upGlow : col.downGlow; c.shadowBlur = 14 * hr; c.globalAlpha = 0.9; c.fillStyle = col[f.up ? "up" : "down"];
        c.fillRect(X - bw / 2, Math.round(f.t * vr), bw, Math.max(1, Math.round((f.b - f.t) * vr)));
      }
      // the last price: a glowing hairline under the series' own dashed price line
      if (gv.py != null && f) {
        c.shadowColor = f.up ? col.upGlow : col.downGlow; c.shadowBlur = 6 * hr; c.globalAlpha = 0.45; c.fillStyle = col[f.up ? "up" : "down"];
        c.fillRect(0, Math.round(gv.py * vr) - Math.floor(vr / 2), bitmapSize.width, Math.max(1, Math.round(vr)));
      }
      // our entry / exit marks: a soft halo where the series draws them
      for (const m of gv.halos) {
        c.shadowColor = m.color; c.shadowBlur = 12 * hr; c.globalAlpha = 0.5; c.fillStyle = m.color;
        c.beginPath(); c.arc(m.x * hr, m.y * vr, 3.5 * hr, 0, Math.PI * 2); c.fill();
      }
      c.restore();
    });
  },
};
return {
  paneViews: () => [{zOrder: () => "bottom", renderer: () => glowR}],
  updateAllViews() {
    gv.bars = []; gv.last = null; gv.py = null; gv.halos = [];
    if (o.onUpdate) o.onUpdate();
    const data = o.data();
    if (!o.ai() || !data.length) return;
    const ts = chart.timeScale(), r = ts.getVisibleLogicalRange();
    if (!r) return;
    const sp = ts.options().barSpacing || 6;
    gv.w = Math.max(1, sp * 0.72);
    const n = data.length, a = Math.max(0, Math.floor(r.from)), z = Math.min(n - 1, Math.ceil(r.to));
    const Y = (p) => series.priceToCoordinate(p);
    for (let i = a; i <= z; i++) {
      const d = data[i], x = ts.logicalToCoordinate(i);
      const yo = Y(d.open), yc = Y(d.close), yh = Y(d.high), yl = Y(d.low);
      if (x == null || yo == null || yc == null || yh == null || yl == null) continue;
      const b = {x, t: Math.min(yo, yc), b: Math.max(yo, yc), hi: yh, lo: yl, up: d.close >= d.open};
      gv.bars.push(b);
      if (i === n - 1) gv.last = b;
    }
    const ld = data[n - 1];
    gv.py = ld ? Y(ld.close) : null;
    const size = Math.min(Math.max(sp, 12), 30), seen = new Set();
    for (const m of o.marks ? o.marks() : []) {
      const i = o.idx(m.time);
      if (i == null || i < a || i > z || m.position === "inBar") continue;
      const k = i + m.position;
      if (seen.has(k)) continue;                           // the first mark of a bar side (stacked ones sit further out)
      seen.add(k);
      const d = data[i], x = ts.logicalToCoordinate(i);
      const y = m.position === "aboveBar" ? Y(d.high) - size / 2 - 3 : Y(d.low) + size / 2 + 3;
      if (x != null && y != null && m.glow !== false) gv.halos.push({x, y, color: m.color});
    }
  },
};}

// the candle glow's soft passes [scale, alpha]: two for a big chart; ONE for a small cell of 여러 차트 (screens/charts.js,
// `lite`), where up to nine charts redraw together
const GLOW_PASSES = [[3, 0.5], [8, 0.6]], LITE_PASSES = [[6, 0.7]];

/** The '선' menu's choices of one deck key on this device: {off: Set of groups, hide: Set of line ids}. The same rule
 *  chartDeck starts from (nothing stored yet: on a phone the position / stop / level / 프리미엄 지표 groups start off,
 *  unless `defaults` says otherwise). The 설정 panel (core/settings.js) reads it and writes {off, hide} back under the
 *  same key ("cfx-" + key) through core/prefs.js, so a deck on screen follows at once. */
export function deckState(key, groups, defaults) {
  const saved = local.get("cfx-" + key, null) || {};
  const defOff = groups.filter((g) => (defaults && g in defaults ? !defaults[g] : (narrow() && ["pos", "risk", "sr", "smc"].includes(g))));
  return {off: new Set(Array.isArray(saved.off) ? saved.off.filter((g) => groups.includes(g)) : defOff),
    hide: new Set(Array.isArray(saved.hide) ? saved.hide.slice(-60) : [])};
}
export {FLASH_KEY};

/** The candle glow alone, for a chart without the deck (매매법 / 계좌 charts): the AI skin only, null otherwise. */
export function candleGlow(chart, series) {
  if (!isAi()) return null;
  const col = colours();
  let data = [];
  const p = glowPrimitive({chart, series, data: () => data, col: () => col, ai: () => true,
    onUpdate: () => { try { data = series.data(); } catch (e) { data = []; } }});
  series.attachPrimitive(p);
  return p;
}

/**
 * chartDeck({chart, series, wrap, box, ctx, key, groups, defaults, tag, lite}) -> deck
 *   wrap: the positioned box around the chart element `box` (the layers sit in it, the pills over the pane)
 *   key: per-device memory name ("term" | "chart" | "grid"); groups: the ids the '선' menu lists (GROUP_KO)
 *   tag: true draws our own last-price tag on the right axis (glows, pulses on a real new price)
 *   lite: a small cell of 여러 차트: the same glow and flash, the glow drawn in one soft pass instead of two
 * deck: {setData, update, setMarkers, setLines, flash, shown(g), onToggle(fn), menuBtn, smcBtn, lightChip, place, ready}
 */
export function chartDeck(o) {
  const {chart, series, wrap, box, ctx} = o;
  const key = "cfx-" + (o.key || "chart");
  const groups = o.groups || ["pos", "risk", "sr", "smc", "ev", "vol"];
  const saved = local.get(key, null) || {};
  const defOff = groups.filter((g) => (o.defaults && g in o.defaults ? !o.defaults[g] : (narrow() && ["pos", "risk", "sr", "smc"].includes(g))));
  const st = {
    off: new Set(Array.isArray(saved.off) ? saved.off.filter((g) => groups.includes(g)) : defOff),
    hide: new Set(Array.isArray(saved.hide) ? saved.hide.slice(-60) : []),
    data: [], col: colours(), ai: isAi(), smc: null, smcAt: null, range: null, zone: null, lastPx: null, raf: 0, marks: [], idx: new Map(),
  };
  const subs = [];
  const save = () => local.set(key, {off: [...st.off], hide: [...st.hide].slice(-60)});
  const shown = (g) => !st.off.has(g);

  // ---------------------------------------------------------------- layers (under the transparent chart canvas)
  wrap.classList.add("cfx");
  wrap.dataset.fx = st.ai ? "ai" : "plain";
  const depth = h("i", {class: "cfx-depth", "aria-hidden": "true"});
  const ambUp = h("i", {class: "cfx-amb", dataset: {tone: "up"}, "aria-hidden": "true"});
  const ambDn = h("i", {class: "cfx-amb", dataset: {tone: "down"}, "aria-hidden": "true"});
  const flashEl = h("i", {class: "cfx-flash", "aria-hidden": "true"});
  const wPrem = h("span", {class: "cfx-zw", dataset: {tone: "down"}}, "Premium");
  const wDisc = h("span", {class: "cfx-zw", dataset: {tone: "up"}}, "Discount");
  const under = h("div", {class: "cfx-under", "aria-hidden": "true"}, depth, ambDn, ambUp, wPrem, wDisc, flashEl);
  const pills = h("div", {class: "cfx-pills"});
  const edgeTop = h("div", {class: "cfx-edge top"}), edgeBot = h("div", {class: "cfx-edge bot"});
  const smcKey = h("div", {class: "cfx-smckey", hidden: true, title: SMC_NOTE}, SMC_KEY);
  const over = h("div", {class: "cfx-over"}, pills, edgeTop, edgeBot, smcKey);
  const tagEl = o.tag ? h("div", {class: "cfx-tag", hidden: true}, h("b", {class: "num"}, "—")) : null;
  wrap.prepend(under);
  wrap.append(over);
  if (tagEl) wrap.append(tagEl);
  box.classList.add("cfx-box");
  if (st.ai) chart.applyOptions({layout: {background: {type: "solid", color: "transparent"}}});

  // ---------------------------------------------------------------- volume (an overlay scale along the bottom)
  let vol = null;
  try {
    vol = chart.addHistogramSeries({priceScaleId: "cfxvol", priceFormat: {type: "volume"}, lastValueVisible: false, priceLineVisible: false});
    chart.priceScale("cfxvol").applyOptions({scaleMargins: {top: 0.86, bottom: 0}, visible: false});
  } catch (e) { vol = null; }
  const hasVol = () => st.data.some((b) => Number(b.volume) > 0);
  const volRow = (b) => ({time: b.time, value: Number(b.volume) || 0, color: b.close >= b.open ? st.col.volUp : st.col.volDown});
  function paintVol() {
    if (!vol) return;
    const on = shown("vol") && hasVol();
    vol.applyOptions({visible: on});
    chart.priceScale("right").applyOptions({scaleMargins: {top: 0.08, bottom: on ? 0.16 : 0.08}});
    if (on) vol.setData(st.data.filter((b) => b.volume != null).map(volRow)); else vol.setData([]);
  }

  // ---------------------------------------------------------------- the glow (under the candles; glowPrimitive below)
  series.attachPrimitive(glowPrimitive({chart, series, data: () => st.data, marks: () => st.marks, idx: (t) => st.idx.get(t),
    col: () => st.col, ai: () => st.ai, onUpdate: () => schedule(), lite: !!o.lite}));

  // ---------------------------------------------------------------- lines (our positions, stops, levels, alerts)
  const lines = new Map();                    // id -> {spec, y, vis}
  const axisViews = [];
  const lineR = {
    draw(target) {
      target.useBitmapCoordinateSpace(({context: c, horizontalPixelRatio: hr, verticalPixelRatio: vr, bitmapSize, mediaSize}) => {
        const col = st.col;
        c.save();
        for (const L of lines.values()) {
          if (!L.vis || L.y == null || L.y < 0 || L.y > mediaSize.height) continue;
          const sp = L.spec, colr = col[sp.tone] || col.flat;
          const y = Math.round(L.y * vr) + 0.5 * (Math.round(vr) % 2), lw = Math.max(1, Math.round(vr));
          c.setLineDash(sp.dash === 1 ? [5 * hr, 4 * hr] : sp.dash === 2 ? [1.5 * hr, 3 * hr] : []);
          c.lineWidth = lw;
          c.strokeStyle = colr;
          if (st.ai && sp.glow !== false) {
            c.shadowColor = sp.tone === "up" ? col.upGlow : sp.tone === "down" ? col.downGlow : col.accentGlow;
            c.shadowBlur = 5 * hr; c.globalAlpha = (sp.alpha ?? 0.6) * 0.7;
            c.beginPath(); c.moveTo(0, y); c.lineTo(bitmapSize.width, y); c.stroke();
            c.shadowBlur = 0;
          }
          c.globalAlpha = sp.alpha ?? 0.6;
          c.beginPath(); c.moveTo(0, y); c.lineTo(bitmapSize.width, y); c.stroke();
        }
        c.restore();
      });
    },
  };
  const linePrim = {
    paneViews: () => [{zOrder: () => "normal", renderer: () => lineR}],
    priceAxisViews: () => axisViews,
    updateAllViews() {
      for (const L of lines.values()) L.y = L.vis ? series.priceToCoordinate(L.spec.price) : null;
      schedule();
    },
  };
  series.attachPrimitive(linePrim);

  const isVis = (sp) => shown(sp.group) && !st.hide.has(sp.id) && !(sp.alias || []).some((x) => st.hide.has(x)) && !(sp.parent && st.hide.has(sp.parent));
  function rebuildAxis() {
    axisViews.length = 0;
    for (const L of lines.values()) {
      if (!L.spec.axis) continue;
      axisViews.push({
        coordinate: () => (L.y == null ? -1000 : L.y), text: () => fmtPrice(L.spec.price), textColor: () => st.col.axisInk,
        backColor: () => st.col[L.spec.tone] || st.col.flat, visible: () => !!L.vis && L.y != null, tickVisible: () => false,
      });
    }
  }
  /**
   * setLines([{id, group, price, tone, dash: 0 | 1 | 2, alpha, axis, label, parent, edge,
   *            pill: {text, title, chips: [{text, ids: [child line ids], title}]}}]) — the whole set of this kind
   *   (``kind`` names the caller's own set, so the terminal's positions and its levels can be set separately).
   */
  function setLines(kind, list) {
    for (const [id, L] of lines) if (L.kind === kind && !list.some((x) => x.id === id)) { lines.delete(id); if (L.pill) L.pill.remove(); }
    for (const sp of list) {
      if (!Number.isFinite(sp.price)) continue;
      const L = lines.get(sp.id) || {kind, y: null, vis: false, pill: null};
      L.kind = kind; L.spec = sp; L.vis = isVis(sp);
      if (sp.pill) L.pill = paintPill(L, L.pill); else if (L.pill) { L.pill.remove(); L.pill = null; }
      lines.set(sp.id, L);
    }
    rebuildAxis();
    linePrim.updateAllViews();
    smcP.request();
    refresh();
  }
  function hideLine(id, on = true) {
    if (on) st.hide.add(id); else st.hide.delete(id);
    save(); revis();
  }
  function revis() {
    for (const L of lines.values()) {
      L.vis = isVis(L.spec);
      if (L.pill) for (const ch of L.pill.querySelectorAll(".cfx-chip")) ch.setAttribute("aria-pressed", String((ch._ids || []).some((x) => !st.hide.has(x))));
    }
    linePrim.updateAllViews(); smcP.request(); paintMenu(); refresh();
  }
  function paintPill(L, old) {
    const sp = L.spec, p = sp.pill;
    const chips = (p.chips || []).map((ch) => {
      const b = h("button", {type: "button", class: "cfx-chip", title: ch.title || `${ch.text} 선 보이기·숨기기`, "aria-pressed": String(ch.ids.some((x) => !st.hide.has(x))),
        onclick: (e) => { e.stopPropagation(); const on = ch.ids.some((x) => !st.hide.has(x)); for (const x of ch.ids) { if (on) st.hide.add(x); else st.hide.delete(x); } save(); revis(); }}, ch.text);
      b._ids = ch.ids;
      return b;
    });
    const el = h("div", {class: "cfx-pill", dataset: {tone: TONES.includes(sp.tone) ? sp.tone : "flat"}, title: (p.title ? p.title + " · " : "") + "누르면 이 선을 숨깁니다 (선 메뉴에서 다시 보기)"},
      h("button", {type: "button", class: "cfx-pt num", onclick: () => hideLine(sp.id)}, p.text), ...chips,
      h("button", {type: "button", class: "cfx-x", "aria-label": "이 선 숨기기", title: "이 선 숨기기", onclick: () => hideLine(sp.id)}, "×"),
      h("span", {class: "cfx-more num", hidden: true}));
    if (old) old.replaceWith(el); else pills.append(el);
    return el;
  }

  // ---------------------------------------------------------------- placing the DOM overlays (one frame per change)
  let pane = {w: 0, h: 0};
  function schedule() {
    if (st.raf) return;
    st.raf = requestAnimationFrame(() => { st.raf = 0; place(); });
  }
  function measure() {
    let sw = 0, th = 0;
    try { sw = chart.priceScale("right").width(); th = chart.timeScale().height(); } catch (e) { /* mid-layout */ }
    pane = {w: Math.max(0, box.clientWidth - sw), h: Math.max(0, box.clientHeight - th), sw, x: box.offsetLeft, y: box.offsetTop};
  }
  function place() {
    measure();
    for (const el of [under, over]) {
      el.style.left = pane.x + "px"; el.style.top = pane.y + "px"; el.style.width = pane.w + "px"; el.style.height = pane.h + "px";
    }
    layoutPills();
    placeSplit();
    if (tagEl) {
      const d = st.data[st.data.length - 1], y = d ? series.priceToCoordinate(d.close) : null;
      if (y == null || y < 0 || y > pane.h) tagEl.hidden = true;
      else {
        tagEl.hidden = false;
        tagEl.style.left = (pane.x + pane.w) + "px"; tagEl.style.width = pane.sw + "px";
        tagEl.style.transform = `translateY(${Math.round(pane.y + y - 10)}px)`;
      }
    }
  }
  function layoutPills() {
    const on = [], above = [], below = [];
    for (const L of lines.values()) {
      if (!L.pill) continue;
      const y = L.vis ? L.y : null;
      if (!L.vis || y == null) { L.pill.hidden = true; continue; }
      if (y < 0) { L.pill.hidden = true; above.push(L); continue; }
      if (y > pane.h) { L.pill.hidden = true; below.push(L); continue; }
      on.push({L, y});
    }
    on.sort((a, b) => a.y - b.y);
    let prev = null, bottom = -Infinity;
    for (const it of on) {
      const want = Math.max(TOP_GAP, it.y - PILL_H / 2);              // under the OHLC legend line
      const top = Math.max(want, bottom + PILL_GAP);
      if (prev && top - want > PILL_H * 1.6) {             // too far from its own line: merge into the pill above
        it.L.pill.hidden = true;
        prev.more.push(it.L);
        continue;
      }
      it.L.pill.hidden = false;
      it.L.pill.style.transform = `translateY(${Math.round(Math.min(top, pane.h - PILL_H))}px)`;
      it.L.pill.classList.toggle("off", Math.abs(top - want) > 1);
      bottom = top + PILL_H;
      prev = {L: it.L, more: []};
      it.prev = prev;
      it.L._grp = prev;
    }
    for (const it of on) {
      if (!it.prev) continue;
      const m = it.L.pill.querySelector(".cfx-more");
      const more = it.prev.more;
      m.hidden = !more.length;
      if (more.length) { m.textContent = `+${more.length}`; m.title = more.map((x) => x.spec.pill.text).join("\n"); }
    }
    paintEdge(edgeTop, above, "▲");
    paintEdge(edgeBot, below, "▼");
  }
  function paintEdge(el, list, arrow) {
    list.sort((a, b) => (arrow === "▲" ? a.spec.price - b.spec.price : b.spec.price - a.spec.price));
    const key = list.map((L) => L.spec.id + L.spec.pill.text).join("|");
    if (el._key === key) return;
    el._key = key;
    el.replaceChildren(...[...list.slice(0, EDGE_MAX).map((L) => h("span", {class: "cfx-em num", dataset: {tone: L.spec.tone}, title: `${L.spec.pill.title || L.spec.pill.text} · 화면 ${arrow === "▲" ? "위" : "아래"}`},
      `${arrow} ${fmtPrice(L.spec.price)} · ${L.spec.pill.short || L.spec.pill.text}`)),
    list.length > EDGE_MAX ? h("span", {class: "cfx-em num", dataset: {tone: "flat"}}, `+${list.length - EDGE_MAX}`) : null].filter(Boolean));
  }

  // ---------------------------------------------------------------- ambient + flash
  let fmode = modeOf(local.get(FLASH_KEY, DEFAULT_FLASH)).id;
  const sched = flashScheduler({
    reduced, visible, mode: () => fmode,
    play(ev, T) {
      if (!st.ai || typeof flashEl.animate !== "function") return;
      flashEl.dataset.tone = ev.tone;
      try {
        if (flashEl._a) flashEl._a.cancel();
        const hold = T - ENVELOPE.inMs - ENVELOPE.outMs;
        flashEl._a = flashEl.animate([{opacity: 0}, {opacity: ev.k, offset: ENVELOPE.inMs / T, easing: "ease-in-out"},
          {opacity: ev.k, offset: (ENVELOPE.inMs + hold) / T, easing: "ease-in"}, {opacity: 0}], {duration: T, easing: "linear"});
      } catch (e) { /* an old browser: no flash */ }
    },
  });
  if (ctx && ctx.track) ctx.track(() => { sched.cancel(); if (flashEl._a) flashEl._a.cancel(); });
  // '번쩍임: 자주 / 보통 / 끄기' (per device; 끄기 keeps the steady tint). Reduced motion: no flash whatever is chosen.
  const flashSel = h("select", {class: "cfx-fsel", "aria-label": "번쩍임", title: FLASH_TIP + "\n번쩍임: 자주 = 큰 체결마다 · 보통 = 고래·큰 청산·우리 체결만 · 끄기",
    onchange: () => { fmode = modeOf(flashSel.value).id; local.set(FLASH_KEY, fmode); if (fmode === "off") sched.cancel(); }},
  FLASH_MODES.map((m) => h("option", {value: m.id}, `번쩍임 ${m.ko}`)));
  flashSel.value = fmode;
  flashSel.hidden = !st.ai;
  const lightChip = h("span", {class: "cfx-light", hidden: !st.ai, tabindex: "0", title: AMBIENT_TIP + "\n" + FLASH_TIP, "aria-label": AMBIENT_TIP + ". " + FLASH_TIP},
    h("i", {"aria-hidden": "true"}), h("span", null, "빛"));
  wPrem.title = AMBIENT_TIP;
  /** The Premium / Discount split at the price scale's current position (called with every redraw: pan, zoom, data). */
  function placeSplit() {
    if (!st.ai || !st.data.length) { under.dataset.split = ""; return; }
    let vis = st.data;
    const r = chart.timeScale().getVisibleLogicalRange();
    if (r) vis = st.data.slice(Math.max(0, Math.floor(r.from)), Math.max(0, Math.ceil(r.to) + 1));
    const sp = splitOf(st.range, vis);
    const y = sp ? series.priceToCoordinate(sp.eq) : null;
    if (y == null) { under.dataset.split = ""; return; }
    const Y = Math.round(Math.max(0, Math.min(pane.h, y)));
    under.dataset.split = "1";
    under.style.setProperty("--split", Y + "px");
    wPrem.hidden = Y < 22; wDisc.hidden = pane.h - Y < 22;
    // the chip says which side the price is on now (and the split's source in its tooltip)
    const z = zoneOf(st.data[st.data.length - 1].close, sp.eq);
    if (z !== st.zone || sp.src !== st.zoneSrc) {
      st.zone = z; st.zoneSrc = sp.src;
      lightChip.dataset.tone = z === "premium" ? "down" : "up";
      lightChip.lastChild.textContent = z === "premium" ? "Premium 구간" : "Discount 구간";
      lightChip.title = `${AMBIENT_TIP}\n나누는 선: ${sp.src === "range" ? "지금 범위의 중간값" : "화면 고가·저가의 중간"} ${fmtPrice(sp.eq)}\n${FLASH_TIP}`;
    }
  }

  // ---------------------------------------------------------------- 프리미엄 지표
  // the words of our lines (저항 / 지지 / 잠금 / 손절 / 알림 …) are placed with the indicators' words at the right edge
  const lineWords = () => [...lines.values()].filter((L) => L.vis && L.spec.label && L.y != null)
    .map((L) => ({s: L.spec.label, price: L.spec.price, c: st.col[L.spec.tone] || st.col.flat}));
  const smcP = smcPrimitive({chart, series, get: () => (shown("smc") ? st.smc : null), col: () => st.col, extra: lineWords,
    zoneWords: () => !st.ai});                             // the AI skin's split already says Premium / Discount
  series.attachPrimitive(smcP);
  function computeSmc() {
    // closed candles only (a forming bar can still change); the AI skin's split uses the dealing range even with the
    // indicator itself turned off
    const need = shown("smc") || st.ai;
    const r = need && st.data.length >= 31 ? smcAll(st.data.slice(0, -1)) : null;
    st.range = r && r.range;
    st.smc = shown("smc") ? r : null;
    st.smcAt = st.data.length ? st.data[st.data.length - 1].time : null;
    smcP.request(); schedule();
  }

  // ---------------------------------------------------------------- the '선' menu + the 프리미엄 지표 button
  const mItems = new Map();
  const hiddenBtn = h("button", {type: "button", class: "cfx-mi cfx-mback", onclick: () => { st.hide.clear(); save(); revis(); }});
  const menu = h("div", {class: "cfx-menu", role: "menu", hidden: true, "aria-label": "차트 선 보이기"},
    groups.map((g) => {
      const b = h("button", {type: "button", class: "cfx-mi", role: "menuitemcheckbox", "aria-checked": String(shown(g)), onclick: () => toggle(g)},
        h("i", {class: "cfx-ck", "aria-hidden": "true"}), GROUP_KO[g] || g);
      mItems.set(g, b);
      return b;
    }),
    h("div", {class: "cfx-mrow"},
      h("button", {type: "button", class: "cfx-mi", onclick: () => setAll(true)}, "모두 보기"),
      h("button", {type: "button", class: "cfx-mi", onclick: () => setAll(false)}, "모두 숨기기")),
    hiddenBtn,
    h("p", {class: "cfx-mnote"}, "선의 이름표를 누르면 그 선만 숨깁니다 · 이 기기에만 기억"));
  const menuBtn = h("button", {type: "button", class: "cfx-mbtn", "aria-haspopup": "menu", "aria-expanded": "false", title: "차트에 보일 선 고르기",
    onclick: (e) => { e.stopPropagation(); openMenu(menu.hidden); }}, "선 ", h("span", {class: "cfx-mcount num"}), " ▾");
  const menuWrap = h("span", {class: "cfx-mwrap"}, menuBtn, menu);
  const smcBtn = groups.includes("smc") ? h("button", {type: "button", class: "cfx-smcbtn", "aria-pressed": String(shown("smc")), title: SMC_NOTE,
    onclick: () => toggle("smc")}, "프리미엄 지표") : null;
  function openMenu(on) {
    menu.hidden = !on;
    menuBtn.setAttribute("aria-expanded", String(on));
    if (on) { paintMenu(); const f = menu.querySelector("button"); if (f) f.focus(); }
  }
  if (ctx && ctx.listen) {
    ctx.listen(document, "pointerdown", (e) => { if (!menu.hidden && !menuWrap.contains(e.target)) openMenu(false); });
    ctx.listen(document, "keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { openMenu(false); menuBtn.focus(); } });
  }
  function paintMenu() {
    for (const [g, b] of mItems) b.setAttribute("aria-checked", String(shown(g)));
    if (smcBtn) smcBtn.setAttribute("aria-pressed", String(shown("smc")));
    const nHid = [...lines.values()].filter((L) => st.hide.has(L.spec.id)).length;
    hiddenBtn.hidden = !nHid;
    hiddenBtn.textContent = `숨긴 선 ${nHid}개 다시 보기`;
    const offN = groups.filter((g) => !shown(g)).length;
    menuBtn.querySelector(".cfx-mcount").textContent = offN || nHid ? `${offN ? "끔 " + offN : ""}${offN && nHid ? " · " : ""}${nHid ? "숨김 " + nHid : ""}` : "";
    smcKey.hidden = !shown("smc") || !st.smc;
  }
  function toggle(g, on = !shown(g)) {
    if (on) st.off.delete(g); else st.off.add(g);
    save(); applyGroup(g);
  }
  function setAll(on) {
    for (const g of groups) if (on) st.off.delete(g); else st.off.add(g);
    if (on) st.hide.clear();
    save();
    for (const g of groups) applyGroup(g, true);
    revis();
    for (const fn of subs) fn(null);
  }
  function applyGroup(g, quiet) {
    if (g === "vol") paintVol();
    if (g === "smc") computeSmc();
    if (!quiet) { revis(); for (const fn of subs) fn(g); }
  }
  function refresh() { paintMenu(); schedule(); }

  // 설정 한 곳 (core/settings.js through core/prefs.js): the panel changes this device's '선' choices and '번쩍임' while
  // the deck is on screen, under the same storage keys as the deck's own menu and select; the deck follows at once
  const prefOffs = [
    onPref(key, (v) => {
      const x = v && typeof v === "object" ? v : {};
      st.off = new Set(Array.isArray(x.off) ? x.off.filter((g) => groups.includes(g)) : []);
      st.hide = new Set(Array.isArray(x.hide) ? x.hide.slice(-60) : []);
      for (const g of groups) applyGroup(g, true);
      revis();
      for (const fn of subs) fn(null);
    }),
    onPref(FLASH_KEY, (v) => {
      fmode = modeOf(v).id;
      if ("value" in flashSel) flashSel.value = fmode;
      if (fmode === "off") sched.cancel();
    }),
  ];
  if (ctx && ctx.track) ctx.track(() => { for (const off of prefOffs) off(); });

  // ---------------------------------------------------------------- data in
  function index() { st.idx = new Map(st.data.map((b, i) => [b.time, i])); }
  function setData(data) {
    st.col = colours();
    st.data = (data || []).slice();
    index();
    series.setData(st.data);
    st.lastPx = null;
    st.zone = null;
    paintVol(); computeSmc(); if (tagEl) paintTag(false); schedule();
  }
  /** A newer or the forming bar. real: the price came from a real new trade / poll (the tag pulses once if it moved). */
  function update(c, real = true) {
    const n = st.data.length, last = st.data[n - 1];
    if (last && c.time < last.time) return false;
    try { series.update(c); } catch (e) { return false; }
    const isNew = !last || c.time > last.time;
    if (isNew) { st.data.push(c); st.idx.set(c.time, st.data.length - 1); } else st.data[n - 1] = {...last, ...c};
    if (vol && shown("vol") && c.volume != null) { try { vol.update(volRow(c)); } catch (e) { /* older */ } }
    if (isNew) computeSmc();
    if (tagEl) paintTag(real);
    schedule();
    return true;
  }
  function paintTag(real) {
    const d = st.data[st.data.length - 1];
    if (!d) return;
    tagEl.firstChild.textContent = fmtPrice(d.close);
    tagEl.dataset.tone = d.close >= d.open ? "up" : "down";
    if (real && st.lastPx != null && d.close !== st.lastPx && !reduced() && visible()) {
      tagEl.removeAttribute("data-hit"); void tagEl.offsetWidth; tagEl.dataset.hit = d.close > st.lastPx ? "up" : "down";
    }
    st.lastPx = d.close;
  }
  if (tagEl) tagEl.addEventListener("animationend", () => tagEl.removeAttribute("data-hit"));
  function setMarkers(marks) {
    st.marks = marks || [];
    series.setMarkers(st.marks.map(({glow, ...m}) => m));
  }

  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => schedule());
    ro.observe(box);
    if (ctx && ctx.track) ctx.track(() => ro.disconnect());
  }
  chart.timeScale().subscribeVisibleLogicalRangeChange(() => schedule());
  if (ctx && ctx.track) ctx.track(() => { if (st.raf) cancelAnimationFrame(st.raf); });
  paintMenu();

  /** Show the most recent ``n`` bars with room on the right for the line labels (like the reference terminal). */
  function showRecent(n = 220, right = 24) {
    const len = st.data.length, ts = chart.timeScale();
    if (len <= n) { ts.fitContent(); ts.scrollToPosition(Math.min(right, Math.round(len / 10)), false); return; }
    ts.setVisibleLogicalRange({from: len - n, to: len - 1 + right});
  }

  return {
    setData, update, setMarkers, setLines, showRecent, place: schedule, shown, data: () => st.data,
    /** A real event of the coin on screen: {tone: "up" | "down" | "accent", k: 0..1, why} (AI skin only). */
    flash(ev) { if (st.ai) sched.push(ev); },
    onToggle(fn) { subs.push(fn); },
    menuBtn: menuWrap, smcBtn, lightChip, flashSel,
  };
}

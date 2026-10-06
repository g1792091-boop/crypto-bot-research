// The chart deck (owners 10/06: "선이 너무 크고 투박하다, 누르면 숨기게, 차트가 비어 보인다, 간지나게"): one helper the
// terminal chart and the 차트 screen share on top of the vendored lightweight-charts (v4.2 series primitives).
//   glow       AI skin only: candles and wicks get a soft neon glow in their up / down colours, the forming candle a
//              little brighter, the last price a glowing line, our entry / exit marks a halo; a faint depth gradient.
//              Drawn under the candles (primitive zOrder "bottom"), so the candles and every text stay crisp.
//   ambient    AI skin only: the pane is washed sky blue while the last close is above the EMA(50) of the bars shown,
//              red below (core/flash.js ambient: it flips only on a real cross), ~1.2 s CSS cross-fade on a change.
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
import {flashScheduler, ambient, ENVELOPE, FLASH_MODES, DEFAULT_FLASH, modeOf} from "./flash.js";
import {smcAll} from "./smc.js";
import {smcPrimitive} from "./smcdraw.js";

export const GROUP_KO = {pos: "포지션 선", risk: "손절·잠금", sr: "지지·저항", smc: "프리미엄 지표", ev: "경제지표", vol: "거래량", al: "가격 알림 선"};
export const AMBIENT_TIP = "빨간 빛 = 가격이 50봉 평균 아래 / 하늘색 = 위";
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
 * chartDeck({chart, series, wrap, box, ctx, key, groups, defaults, tag}) -> deck
 *   wrap: the positioned box around the chart element `box` (the layers sit in it, the pills over the pane)
 *   key: per-device memory name ("term" | "chart"); groups: the ids the '선' menu lists (GROUP_KO)
 *   tag: true draws our own last-price tag on the right axis (glows, pulses on a real new price)
 * deck: {setData, update, setMarkers, setLines, flash, shown(g), onToggle(fn), menuBtn, smcBtn, lightChip, place, ready}
 */
export function chartDeck(o) {
  const {chart, series, wrap, box, ctx} = o;
  const key = "cfx-" + (o.key || "chart");
  const groups = o.groups || ["pos", "risk", "sr", "smc", "ev", "vol"];
  const saved = local.get(key, null) || {};
  const defOff = groups.filter((g) => (o.defaults && g in o.defaults ? !o.defaults[g] : (narrow() && ["pos", "sr", "smc"].includes(g))));
  const st = {
    off: new Set(Array.isArray(saved.off) ? saved.off.filter((g) => groups.includes(g)) : defOff),
    hide: new Set(Array.isArray(saved.hide) ? saved.hide.slice(-60) : []),
    data: [], col: colours(), ai: isAi(), smc: null, smcAt: null, amb: null, lastPx: null, raf: 0, marks: [], idx: new Map(),
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
  const under = h("div", {class: "cfx-under", "aria-hidden": "true"}, depth, ambUp, ambDn, flashEl);
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

  // ---------------------------------------------------------------- the glow primitive (under the candles)
  const gv = {bars: [], last: null, w: 2, py: null, halos: []};
  const glowR = {
    draw() {},
    drawBackground(target) {
      if (!st.ai || !gv.bars.length) return;
      target.useBitmapCoordinateSpace(({context: c, horizontalPixelRatio: hr, verticalPixelRatio: vr, bitmapSize}) => {
        const col = st.col;
        const paths = {up: new Path2D(), down: new Path2D()};
        const bw = Math.max(1, Math.round(gv.w * hr)), wl = Math.max(1, Math.floor(hr));
        for (const b of gv.bars) {
          const p = paths[b.up ? "up" : "down"], X = Math.round(b.x * hr);
          p.rect(X - bw / 2, Math.round(b.t * vr), bw, Math.max(1, Math.round((b.b - b.t) * vr)));
          p.rect(X - wl / 2, Math.round(b.hi * vr), wl, Math.max(1, Math.round((b.lo - b.hi) * vr)));
        }
        c.save();
        for (const tone of ["up", "down"]) {
          c.shadowColor = tone === "up" ? col.upGlow : col.downGlow;
          c.shadowBlur = 7 * hr;
          c.globalAlpha = 0.55;
          c.fillStyle = col[tone];
          c.fill(paths[tone]);
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
  const glowPrim = {
    paneViews: () => [{zOrder: () => "bottom", renderer: () => glowR}],
    updateAllViews() {
      gv.bars = []; gv.last = null; gv.py = null; gv.halos = [];
      schedule();
      if (!st.ai || !st.data.length) return;
      const ts = chart.timeScale(), r = ts.getVisibleLogicalRange();
      if (!r) return;
      const sp = ts.options().barSpacing || 6;
      gv.w = Math.max(1, sp * 0.72);
      const n = st.data.length, a = Math.max(0, Math.floor(r.from)), z = Math.min(n - 1, Math.ceil(r.to));
      const Y = (p) => series.priceToCoordinate(p);
      for (let i = a; i <= z; i++) {
        const d = st.data[i], x = ts.logicalToCoordinate(i);
        const yo = Y(d.open), yc = Y(d.close), yh = Y(d.high), yl = Y(d.low);
        if (x == null || yo == null || yc == null || yh == null || yl == null) continue;
        const b = {x, t: Math.min(yo, yc), b: Math.max(yo, yc), hi: yh, lo: yl, up: d.close >= d.open};
        gv.bars.push(b);
        if (i === n - 1) gv.last = b;
      }
      const ld = st.data[n - 1];
      gv.py = ld ? Y(ld.close) : null;
      const size = Math.min(Math.max(sp, 12), 30), seen = new Set();
      for (const m of st.marks) {
        const i = st.idx.get(m.time);
        if (i == null || i < a || i > z || m.position === "inBar") continue;
        const k = i + m.position;
        if (seen.has(k)) continue;                           // the first mark of a bar side (stacked ones sit further out)
        seen.add(k);
        const d = st.data[i], x = ts.logicalToCoordinate(i);
        const y = m.position === "aboveBar" ? Y(d.high) - size / 2 - 3 : Y(d.low) + size / 2 + 3;
        if (x != null && y != null && m.glow !== false) gv.halos.push({x, y, color: m.color});
      }
    },
  };
  series.attachPrimitive(glowPrim);

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
  function paintAmbient(fresh) {
    if (!st.ai) { under.dataset.amb = ""; return; }
    const closed = st.data;                               // the forming bar counts: the light follows the price now
    const a = ambient(closed, fresh ? null : st.amb && st.amb.tone);
    if (!a) { under.dataset.amb = ""; return; }
    const changed = !st.amb || st.amb.tone !== a.tone || Math.abs(st.amb.k - a.k) >= 0.05;
    if (!changed && !fresh) return;
    if (fresh) under.classList.add("still");
    under.dataset.amb = a.tone;
    under.style.setProperty("--ak", String(a.k));
    lightChip.dataset.tone = a.tone;
    lightChip.lastChild.textContent = a.tone === "up" ? "평균 위" : "평균 아래";
    st.amb = a;
    if (fresh) requestAnimationFrame(() => requestAnimationFrame(() => under.classList.remove("still")));
  }

  // ---------------------------------------------------------------- 프리미엄 지표
  // the words of our lines (저항 / 지지 / 잠금 / 손절 / 알림 …) are placed with the indicators' words at the right edge
  const lineWords = () => [...lines.values()].filter((L) => L.vis && L.spec.label && L.y != null)
    .map((L) => ({s: L.spec.label, price: L.spec.price, c: st.col[L.spec.tone] || st.col.flat}));
  const smcP = smcPrimitive({chart, series, get: () => (shown("smc") ? st.smc : null), col: () => st.col, extra: lineWords});
  series.attachPrimitive(smcP);
  function computeSmc() {
    if (!shown("smc") || st.data.length < 30) { st.smc = null; smcP.request(); return; }
    st.smc = smcAll(st.data.slice(0, -1));                // closed candles only: a forming bar can still change
    st.smcAt = st.data.length ? st.data[st.data.length - 1].time : null;
    smcP.request();
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

  // ---------------------------------------------------------------- data in
  function index() { st.idx = new Map(st.data.map((b, i) => [b.time, i])); }
  function setData(data) {
    st.col = colours();
    st.data = (data || []).slice();
    index();
    series.setData(st.data);
    st.lastPx = null;
    paintVol(); computeSmc(); paintAmbient(true); if (tagEl) paintTag(false); schedule();
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
    paintAmbient(false);
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

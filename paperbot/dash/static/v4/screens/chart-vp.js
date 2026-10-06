// 매물대 (volume profile) on the 차트 screen and the 터미널 chart (owners 10/06: "매수 물량 구간, 매도 물량 구간들도 중요하게
// 생각하는데"): a horizontal volume-by-price histogram at the right side of the price pane over the visible bars (or
// 오늘 / 최근 7일), each price row split into 매수 (taker buy volume, the candles' "buy" key) and 매도 (volume - buy)
// in the up / down colours, the POC (가장 많이 거래된 가격) line, the 70 % value area (VAH / VAL lines, softly shaded) and,
// to compare, the bot's own 매물대 levels (/api/v4/vplevels: the same function that records kinds 51-53 with every
// signal). The math is chart-vp-calc.js (pure, tested in node); this file draws it and wires it into the chart deck.
//   * It is a group of the chart deck's '선' menu ("매물대", core/chartfx.js groups): OFF by default on the 터미널 (the
//     declutter), ON on a PC window's 차트 screen, remembered per device by the deck like every other group.
//   * Drawn by a series primitive under the candles (zOrder "bottom"; the labels on top), semi-transparent; it stops
//     short of the right-edge names (core/chartfx.js .cfx-name column, measured, never overlapped).
//   * Honest: the volume of each bar is spread evenly over its high-low range (APPROX, in the legend's tooltip); with no
//     "buy" key (an older server) it shows the total only and says so; a range or the bot's lines that fail to load
//     say "불러오지 못했습니다", never an empty or flat profile.
//   * Cost: the whole profile is recomputed at most once a second for live bar changes (throttle), at once for a pan,
//     zoom, resize, range or coin change (it is a few thousand additions). 오늘 / 최근 7일 read /api/candles (5m / 15m
//     bars) once a minute while on; the bot's levels once every two minutes.
import {h, put, ui, fmt, local, tok, serverNow, GROUP_KO} from "../core/pb.js";
import {RANGES, RANGE_KO, APPROX, LEVEL_TFS, MIN_GAP_MS, rowCount, rangeSpec, visibleIdx, buildProfile, rowText, throttle, placeLabels, withVpDefault} from "./chart-vp-calc.js";

GROUP_KO.vp = "매물대";                 // the deck's '선' menu lists a group by this name
const PREF = "vp-";                     // per device: {range, bot} (on / off itself is the deck's)
const MEASURE_MS = 500;
const fontOf = (col, vr, w = 600) => `${w} ${col.fs * vr}px ${col.font}`;

/** The vp group's start state on a device that saved its deck choices before this group existed (the deck would treat a
 *  group it never saw as on): once per device and chart ("term" | "chart"), a device whose saved choices lack "vp" gets it
 *  switched off when the chart's default is off. Call before chartDeck(). */
export function vpPrepare(key, defaultOn) {
  if (local.get(PREF + "seen-" + key, false)) return;
  local.set(PREF + "seen-" + key, true);
  const raw = local.get("cfx-" + key, null);               // core/chartfx.js: "cfx-" + o.key
  const next = withVpDefault(raw, defaultOn);
  if (next !== raw) local.set("cfx-" + key, next);
}

function colours() {
  const c = {};
  for (const [k, n] of [["up", "--up"], ["down", "--down"], ["flat", "--muted"], ["warn", "--warn"], ["accent", "--accent"], ["ink", "--ink-2"],
    ["bg", "--bg"], ["font", "--f-term"], ["fs", "--t-2xs"]]) c[k] = tok(n);
  c.fs = parseFloat(c.fs) || 12;
  return c;
}
/** A volume (the coin's own units) with the digits it needs: 12.35 · 128 · 4,215 · 1.3M. */
export function volText(x) {
  const a = Math.abs(Number(x));
  if (!Number.isFinite(a)) return "—";
  return a >= 1e6 ? fmt.compact(x) : a >= 100 ? fmt.int(x) : a >= 10 ? fmt.num(x, 1) : a >= 1 ? fmt.num(x, 2) : fmt.num(x, 3);
}

/**
 * vpAttach({chart, series, deck, wrap, box, ctx, key, host, legend, sym, tf}) -> {key (the legend row, also appended to
 * ``host``), refresh()}
 *   deck: the screen's chartDeck (groups include "vp"); sym() / tf(): the coin and interval on screen; key: "term" | "chart";
 *   legend: the screen's OHLC legend element over the chart (the labels keep under it when it reaches their column).
 */
export function vpAttach(o) {
  const {chart, series, deck, wrap, box, ctx} = o;
  const saved = local.get(PREF + o.key, null) || {};
  const st = {
    range: RANGES.some((r) => r.id === saved.range) ? saved.range : "view", bot: saved.bot !== false,
    col: colours(), prof: null, structSig: "", liveSig: "", rb: null, rkey: "", rseq: 0, rerr: null, rbusy: false,
    botLv: null, bkey: "", berr: null, hover: -1, res: 0, resAt: 0, resDirty: true, computes: 0, paneW: 0, paneH: 0, symTf: "", metaTxt: null,
  };
  const savePref = () => local.set(PREF + o.key, {range: st.range, bot: st.bot});
  let api = null, g = null, inView = false;
  const on = () => deck.shown("vp");
  const redraw = () => { if (api) api.requestUpdate(); };

  // ---------------------------------------------------------------- the legend row and the hover tip
  const rangeSeg = ui.seg(RANGES.map((r) => ({id: r.id, label: r.ko, title: r.id === "view" ? "지금 차트에 보이는 봉" : r.id === "today" ? "한국 시각 0시부터 지금까지 (5분 봉으로 계산)" : "지난 7일 (15분 봉으로 계산)"})),
    st.range, (id) => setRange(id), {label: "매물대 계산 구간"});
  rangeSeg.classList.add("vp-seg");
  const botBtn = h("button", {type: "button", class: "vp-chip", "aria-pressed": String(st.bot), onclick: () => { st.bot = !st.bot; savePref(); paintKey(); if (st.bot) loadBot(); redraw(); }}, "봇 기준선");
  const meta = h("span", {class: "vp-meta num", role: "status"});
  const retry = h("button", {type: "button", class: "vp-retry", hidden: true, onclick: () => { st.rkey = ""; st.bkey = ""; st.rerr = null; st.berr = null; paintKey(); redraw(); }}, "다시 시도");
  const info = ui.infoTip(`${APPROX}. 가격 칸 하나하나의 매수 = 시장가로 산 물량(테이커 매수), 매도 = 전체 − 매수. `
    + "POC = 가장 많이 거래된 가격, 70% 구간 = POC에서 위·아래로 한 칸씩(물량이 더 많은 쪽부터) 넓혀 전체의 70%를 채운 구간 (위 끝 VAH, 아래 끝 VAL). "
    + "봇 기준선 = 봇이 진입 판단에 쓰는 매물대 (바로 직전 닫힌 200봉을 50칸으로 나눈 값, 칸마다 봉의 종가 부근 가격에 몰아 계산): 이 화면의 매물대와 계산법이 달라 조금 다를 수 있습니다. 참고용이며 매매 신호가 아닙니다.", "매물대 설명");
  const keyEl = h("div", {class: "vp-key", hidden: true, role: "group", "aria-label": "매물대 범례"},
    h("b", {class: "vp-ttl", title: APPROX}, "매물대"), rangeSeg,
    h("span", {class: "vp-sw buy", title: "매수 물량: 시장가로 산 쪽 (테이커 매수)"}, "매수"),
    h("span", {class: "vp-sw sell", title: "매도 물량: 시장가로 판 쪽 (전체 − 매수)"}, "매도"),
    h("span", {class: "vp-sw tot", title: "이 자료에는 매수·매도 구분이 없어 거래량 합계만 그립니다"}, "거래량 합계"),
    h("span", {class: "vp-sw poc", title: "POC: 이 구간에서 가장 많이 거래된 가격"}, "POC 가장 많이 거래된 가격"),
    h("span", {class: "vp-sw va", title: "거래량의 70%가 모인 구간: 위 끝 VAH, 아래 끝 VAL"}, "70% 구간"),
    botBtn, meta, retry, info);
  if (o.host) o.host.append(keyEl);
  const tip = h("div", {class: "vp-tip num", hidden: true, role: "tooltip"});
  wrap.append(tip);

  function paintKey() {
    rangeSeg.set(st.range);
    botBtn.setAttribute("aria-pressed", String(st.bot));
    const t = o.tf();
    const botOk = LEVEL_TFS.includes(t);
    botBtn.disabled = !botOk;
    botBtn.title = botOk ? "봇이 쓰는 매물대 세 줄 (매물 최다 가격 · 위 끝 · 아래 끝) 보이기·숨기기. 이 화면의 매물대와 비교해 보세요."
      : "봇은 15분 · 30분 · 1시간 · 4시간 봉에서만 매물대를 씁니다";
    const p = st.prof, stats = [], notes = [];
    keyEl.dataset.split = p && p.ok && !p.split ? "0" : "1";
    if (st.range !== "view" && st.rbusy && !st.rb) notes.push(`${RANGE_KO[st.range]} 불러오는 중…`);
    else if (st.rerr) notes.push(`${RANGE_KO[st.range]} 자료를 불러오지 못했습니다`);
    else if (p && p.ok) {
      stats.push(`봉 ${fmt.int(p.bars)}개`);
      if (p.split) stats.push(`매수 비율 ${fmt.num(p.buyRatio * 100, 0)}%`); else notes.push("합계만 (이 자료에는 매수·매도 구분이 없습니다)");
    } else if (p && p.why === "novol") notes.push("이 봉들에는 거래량 자료가 없습니다");
    else if (p && p.why === "flat") notes.push("가격 변화가 없어 칸을 나눌 수 없습니다");
    else if (!p) notes.push("계산 중…");
    if (st.bot && botOk && st.berr) notes.push("봇 기준선을 불러오지 못했습니다");
    else if (st.bot && botOk && st.botLv && st.botLv.why) notes.push("봇 기준선: 봉이 모자라 계산하지 못했습니다");
    const txt = [...stats, ...notes].join(" · ");
    if (txt !== st.metaTxt) { st.metaTxt = txt; put(meta, txt); meta.dataset.note = notes.length ? "1" : ""; }     // (a pan recomputes often: touch the DOM only for news)
    const bad = !!(st.rerr || (st.bot && botOk && st.berr));
    meta.classList.toggle("bad", bad);
    retry.hidden = !bad;
  }

  // ---------------------------------------------------------------- data: the bars, the chosen range, the bot's lines
  function setRange(id) {
    if (!RANGES.some((r) => r.id === id) || id === st.range) return;
    st.range = id; st.rerr = null; savePref(); paintKey(); redraw();
  }
  async function loadRange() {
    const spec = rangeSpec(st.range, serverNow() / 1000), sym = o.sym();
    if (!spec) return;
    const tokn = ++st.rseq;
    st.rkey = `${spec.mode}|${sym}`; st.rbusy = true; st.rerr = null; paintKey();
    try {
      const rows = await ctx.api(`/api/candles?symbol=${sym}&interval=${spec.interval}&limit=${spec.limit}`);
      if (tokn !== st.rseq || !ctx.alive()) return;
      st.rb = {sym, mode: spec.mode, rows: (Array.isArray(rows) ? rows : []).filter((r) => r.time >= spec.from), seq: tokn};
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (tokn !== st.rseq || !ctx.alive()) return;
      st.rerr = true; st.rb = null;
    }
    st.rbusy = false; paintKey(); redraw();
  }
  async function loadBot() {
    const sym = o.sym(), tf = o.tf();
    st.bkey = `${sym}|${tf}`;
    if (!st.bot || !LEVEL_TFS.includes(tf)) { st.botLv = null; st.berr = null; paintKey(); return; }
    const bk = st.bkey;
    try {
      const d = await ctx.api(`/api/v4/vplevels?symbol=${sym}&tf=${tf}`);
      if (bk !== st.bkey || !ctx.alive()) return;
      st.botLv = d && d.ready ? {sym, tf, levels: d.levels || [], bars: d.bars, bin: d.bins, stale: !!d.stale} : {sym, tf, why: (d && d.why) || "bars", levels: []};
      st.berr = null;
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (bk !== st.bkey || !ctx.alive()) return;
      st.berr = true; st.botLv = null;
    }
    paintKey(); redraw();
  }

  // ---------------------------------------------------------------- what to compute, when
  /** The bars of the chosen range and the numbers that say whether they (struct) or just their newest bar (live) changed. */
  function select(H) {
    const data = deck.data(), s = o.sym(), t = o.tf(), rows = rowCount(H);
    let list = null, i0 = 0, i1 = -1, seq = 0;
    if (st.range === "view") {
      let rg = null;
      try { rg = chart.timeScale().getVisibleLogicalRange(); } catch (e) { rg = null; }
      const ix = visibleIdx(data, rg);
      if (ix) { list = data; i0 = ix[0]; i1 = ix[1]; }
    } else if (st.rb && st.rb.sym === s && st.rb.mode === st.range) { list = st.rb.rows; i0 = 0; i1 = list.length - 1; seq = st.rb.seq; }
    const first = list && i1 >= i0 ? list[i0] : null, last = list && i1 >= i0 ? list[i1] : null;
    return {list, i0, i1, rows,
      struct: [st.range, s, t, rows, i1 - i0, first ? first.time : 0, st.range === "view" ? 0 : seq].join("|"),
      live: last ? [last.time, last.high, last.low, last.volume, last.buy].join(":") : ""};
  }
  function recompute(sel) {
    st.computes++;
    keyEl.dataset.computes = String(st.computes);                                // (what the browser checks read: how often the profile was rebuilt)
    st.prof = sel.list && sel.i1 >= sel.i0 ? buildProfile(sel.list.slice(sel.i0, sel.i1 + 1), {n: sel.rows}) : {ok: false, why: "nobars"};
    paintKey();
  }
  // live changes of the newest bar (the 5 s poll, the relay's trades): the whole profile at most once per MIN_GAP_MS
  const gate = throttle(() => { recompute(select(st.paneH)); if (!inView) redraw(); }, MIN_GAP_MS);
  ctx.track(() => gate.cancel());

  function ensureLoads() {
    const s = o.sym(), t = o.tf();
    if (st.range !== "view" && st.rkey !== `${st.range}|${s}` && !st.rbusy) loadRange();
    if (st.bot && st.bkey !== `${s}|${t}`) loadBot();
  }

  // ---------------------------------------------------------------- geometry (media pixels) for the renderers
  /** The names column at the pane's right edge (core/chartfx.js): room for "손절 ×2"-sized tags at least, wider when a
   *  longer one is shown (measured at most twice a second; it only grows until the coin or interval changes). */
  function reserve(W) {
    const base = Math.min(Math.round(st.col.fs * 5.4 + 14), Math.round(W * 0.24));
    const now = Date.now();
    if (st.resDirty || now - st.resAt > 4000) {
      st.resDirty = false; st.resAt = now;
      let r = base;
      for (const el of wrap.querySelectorAll(".cfx-name:not([hidden])")) r = Math.max(r, el.offsetWidth + 12);
      st.res = Math.max(st.res, r);
    }
    return Math.min(Math.max(st.res, base), Math.round(W * 0.4));
  }
  function place(W, H) {
    g = null;
    const p = st.prof;
    if (!p || !p.ok) return;
    const Y = (v) => series.priceToCoordinate(v);
    const x1 = W - reserve(W), maxW = Math.max(56, Math.min(240, W * (W < 420 ? 0.22 : 0.16)));
    if (x1 < 120) return;
    const rows = [];
    for (let i = 0; i < p.n; i++) {
      const yb = Y(p.lo + i * p.step), yt = Y(p.lo + (i + 1) * p.step);
      if (yb == null || yt == null || yb < 0 || yt > H) continue;
      const tot = p.tot[i];
      rows.push({i, y0: yt, y1: yb, len: p.max > 0 ? (tot / p.max) * maxW : 0, buyLen: p.split && p.max > 0 ? (p.buy[i] / p.max) * maxW : 0});
    }
    const yAt = (v) => { const y = Y(v); return y == null || y < -2 || y > H + 2 ? null : y; };
    const poc = {y: yAt(p.pocPrice), price: p.pocPrice}, vah = {y: yAt(p.vah), price: p.vah}, val = {y: yAt(p.val), price: p.val};
    // the bot's lines (only for the coin and interval on screen)
    const bot = [];
    const bl = st.bot && st.botLv && st.botLv.sym === o.sym() && st.botLv.tf === o.tf() ? st.botLv : null;
    for (const L of (bl && bl.levels) || []) { const y = yAt(L.price); if (y != null) bot.push({y, price: L.price, kind: L.kind, ko: L.ko}); }
    // the names: ours (POC · VAH · VAL) and the bot's, none closer than a line of text, inside the pane
    const fs = st.col.fs, LH = Math.round(fs * 1.3 + 2);
    const labs = [];
    const lab = (text, y, dy, color, bold) => { if (y != null) labs.push({text, y: y + dy, color, bold}); };
    lab(`POC ${fmt.price(poc.price)}`, poc.y, -LH * 0.6, "warn", true);
    lab(`VAH ${fmt.price(vah.price)}`, vah.y, -LH * 0.6, "warn");
    lab(`VAL ${fmt.price(val.price)}`, val.y, LH * 0.6, "warn");
    for (const b of bot) lab(`봇 ${b.kind === 51 ? "최다가" : b.kind === 52 ? "위 끝" : "아래 끝"} ${fmt.price(b.price)}`, b.y, b.kind === 53 ? LH * 0.6 : -LH * 0.6, "ink");
    labs.splice(Math.max(2, Math.floor(H / (LH * 2.4))));           // a short pane keeps only the first few (POC, VAH, VAL, then the bot's): the labels never fill it
    // the screen's OHLC legend (top left) runs over the labels' column on a narrow pane: the labels start under it
    let top = 2;
    const lg = o.legend;
    if (lg && lg.textContent && lg.offsetLeft + lg.offsetWidth - box.offsetLeft > x1 - 150) top = Math.max(top, lg.offsetTop + lg.offsetHeight - box.offsetTop + 2);
    placeLabels(labs, LH, top, H - 2);
    g = {x1, x0: x1 - maxW, maxW, W, H, rows, poc, vah, val, bot, labs};
    st.paneW = W;
  }

  // ---------------------------------------------------------------- the primitive
  function view() {
    g = null;
    if (!on() || !api) return;
    let W = 0, H = 0;
    try { W = chart.timeScale().width(); H = Math.max(0, box.clientHeight - chart.timeScale().height()); } catch (e) { return; }
    if (!(W > 160 && H > 80)) return;
    st.paneH = H;
    inView = true;
    try {
      const sk = `${o.sym()}|${o.tf()}`;
      if (sk !== st.symTf) { st.symTf = sk; st.res = 0; st.resDirty = true; }          // the names column is measured afresh for a new coin / interval
      const sel = select(H);
      if (sel.struct !== st.structSig) { st.structSig = sel.struct; st.liveSig = sel.live; gate.cancel(); recompute(sel); }
      else if (sel.live !== st.liveSig) { st.liveSig = sel.live; gate.poke(); }
      ensureLoads();
      place(W, H);
    } finally { inView = false; }
  }
  const barsR = {
    draw() {},
    drawBackground(target) {
      const gg = g, p = st.prof;
      if (!gg || !p || !p.ok) return;
      target.useBitmapCoordinateSpace(({context: c, horizontalPixelRatio: hr, verticalPixelRatio: vr, bitmapSize}) => {
        const col = st.col, wBit = bitmapSize.width, lw = Math.max(1, Math.round(vr));
        const line = (y, a, dash, wide) => {
          const yy = Math.round(y * vr) + 0.5 * (lw % 2);
          c.setLineDash(dash ? [4 * hr, 4 * hr] : []);
          c.globalAlpha = a; c.lineWidth = lw;
          c.beginPath(); c.moveTo(wide ? 0 : Math.round(gg.x0 * hr), yy); c.lineTo(wide ? wBit : Math.round(gg.x1 * hr), yy); c.stroke();
        };
        c.save();
        // the 70 % value area: a soft band across the pane, its two edges dashed
        if (gg.vah.y != null || gg.val.y != null) {
          const yt = gg.vah.y == null ? 0 : gg.vah.y, yb = gg.val.y == null ? gg.H : gg.val.y;
          c.globalAlpha = 0.06; c.fillStyle = col.warn;
          c.fillRect(0, Math.round(yt * vr), wBit, Math.max(1, Math.round((yb - yt) * vr)));
        }
        c.strokeStyle = col.warn;
        if (gg.vah.y != null) line(gg.vah.y, 0.45, true, true);
        if (gg.val.y != null) line(gg.val.y, 0.45, true, true);
        // the rows: 매수 next to the right edge, 매도 on its left; the value area brighter, the POC row brightest
        const xr = Math.round(gg.x1 * hr);
        for (const r of gg.rows) {
          const inVa = r.i >= p.vaLo && r.i <= p.vaHi, isPoc = r.i === p.poc, hov = r.i === st.hover;
          const a = (isPoc ? 0.8 : inVa ? 0.52 : 0.27) + (hov ? 0.22 : 0);
          const top = Math.round(r.y0 * vr), hgt = Math.max(1, Math.round(r.y1 * vr) - top - 1);
          const lt = Math.max(1, Math.round(r.len * hr)), lb = Math.round(r.buyLen * hr);
          if (hov) { c.globalAlpha = 0.14; c.fillStyle = col.ink; c.fillRect(Math.round(gg.x0 * hr), top, xr - Math.round(gg.x0 * hr), hgt); }      // the row under the pointer
          c.globalAlpha = Math.min(1, a);
          if (p.split) {
            c.fillStyle = col.up; c.fillRect(xr - lb, top, lb, hgt);
            c.fillStyle = col.down; c.fillRect(xr - lt, top, lt - lb, hgt);
          } else { c.fillStyle = col.flat; c.fillRect(xr - lt, top, lt, hgt); }
          if (hov || isPoc) { c.globalAlpha = hov ? 0.95 : 0.7; c.strokeStyle = hov ? col.ink : col.warn; c.lineWidth = 1; c.strokeRect(xr - lt + 0.5, top + 0.5, lt - 1, Math.max(1, hgt - 1)); }
        }
        c.strokeStyle = col.warn;
        if (gg.poc.y != null) line(gg.poc.y, 0.7, false, true);
        // the bot's lines across the histogram's width only (dashed, the ink colour: not ours)
        c.strokeStyle = col.ink;
        for (const b of gg.bot) line(b.y, 0.85, true, false);
        c.restore();
      });
    },
  };
  const textR = {
    draw(target) {
      const gg = g;
      if (!gg || !gg.labs.length) return;
      target.useBitmapCoordinateSpace(({context: c, horizontalPixelRatio: hr, verticalPixelRatio: vr}) => {
        const col = st.col;
        c.save();
        c.textAlign = "right"; c.textBaseline = "middle";
        c.shadowColor = col.bg; c.shadowBlur = 3 * hr;
        for (const L of gg.labs) {
          c.font = fontOf(col, vr, L.bold ? 700 : 600);
          c.fillStyle = col[L.color] || col.ink;
          c.fillText(L.text, Math.round((gg.x1 - 4) * hr), Math.round(L.ly * vr));
        }
        c.restore();
      });
    },
  };
  const prim = {
    attached(p) { api = p; },
    detached() { api = null; },
    paneViews: () => [{zOrder: () => "bottom", renderer: () => barsR}, {zOrder: () => "top", renderer: () => textR}],
    updateAllViews: view,
  };
  series.attachPrimitive(prim);

  // ---------------------------------------------------------------- hover: '가격 a~b · 매수 x · 매도 y · 매수 비율 z%'
  function hideTip() {
    if (!tip.hidden) tip.hidden = true;
    if (st.hover !== -1) { st.hover = -1; redraw(); }
  }
  chart.subscribeCrosshairMove((p) => {
    const pt = p && p.point, gg = g, pr = st.prof;
    if (!gg || !pr || !pr.ok || !pt || pt.x < gg.x0 || pt.x > gg.x1 + 2) { hideTip(); return; }
    const r = gg.rows.find((q) => pt.y >= q.y0 && pt.y <= q.y1);
    if (!r) { hideTip(); return; }
    const txt = rowText(pr, r.i, {price: fmt.price, vol: (x) => `${volText(x)} ${fmt.coin(o.sym())}`}) + (r.i === pr.poc ? " · POC (가장 많이 거래된 가격)" : "");
    if (tip.textContent !== txt) tip.textContent = txt;
    tip.hidden = false;
    const w = tip.offsetWidth, ox = box.offsetLeft, oy = box.offsetTop;
    tip.style.transform = `translate(${Math.round(ox + Math.max(8, Math.min(gg.x1 - w - 8, pt.x - w - 14)))}px, ${Math.round(oy + Math.max(6, Math.min(gg.H - 34, pt.y - 40)))}px)`;
    if (st.hover !== r.i) { st.hover = r.i; redraw(); }
  });

  // ---------------------------------------------------------------- on / off, the clocks
  function sync() {
    const live = on();
    keyEl.hidden = !live;
    if (live) { st.structSig = ""; paintKey(); } else { tip.hidden = true; st.hover = -1; }
    redraw();
  }
  deck.onToggle((grp) => { if (grp === "vp" || grp == null) sync(); });
  // the names column changed (a longer name, a name gone): measure again at the next draw
  const namesEl = wrap.querySelector(".cfx-names");
  if (namesEl && typeof MutationObserver === "function") {
    const mo = new MutationObserver(() => { st.resDirty = true; if (on()) redraw(); });
    mo.observe(namesEl, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["hidden"]});
    ctx.track(() => mo.disconnect());
  }
  ctx.every(60000, () => { if (on() && st.range !== "view" && !st.rbusy) { st.rkey = ""; redraw(); } }, {now: false});     // 오늘 / 7일: fresh once a minute
  ctx.every(120000, () => { if (on() && st.bot) { st.bkey = ""; redraw(); } }, {now: false});                          // the bot's lines: every two minutes
  sync();
  return {key: keyEl, refresh: redraw, stats: () => ({computes: st.computes, range: st.range, bot: st.bot})};
}

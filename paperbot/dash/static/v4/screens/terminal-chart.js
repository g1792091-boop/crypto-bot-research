// 터미널 centre: the candle chart with the same engine and helpers as 차트 (core/lwc makeChart / candleOptions / tok /
// priceDec, positions-kit normPos): /api/candles (500 bars, then the forming bar every 5 s like 차트), our open positions
// on this coin as entry lines (기존 36 · 5분봉 · 추가 계좌; stops when few enough to read), our recent closed trades as
// entry / exit marks, support / resistance (/api/levels, the four house timeframes), US macro releases as marks with a
// tooltip, and the price tag on the right axis: the last price, dashed across the chart, with the bar-close countdown
// under it; it glows teal / pink when the server's price really moved. A small dot breathes on the last candle while the
// stream is live (never while the page is hidden or under reduced motion).
// Our entry and stop lines carry a soft glow (gap batch B): lightweight-charts price lines cannot glow, so a thin band
// per line sits in an overlay over the chart at the line's price (series.priceToCoordinate, moved with the price tag
// in place()), in the line's own meaning colour (--up-glow / --down-glow, --accent-glow before a mark price). It is
// static; a glow that newly appears (a real new position or stop) draws itself in once (motion.drawIn: skipped under
// reduced motion and on a hidden page). No position on this coin: no line, no glow.
import {h, put, ui, fmt, store, motion, bars, serverNow, stream, makeChart, candleOptions, tok, priceDec} from "../core/pb.js";
import {normPos} from "./positions-kit.js";
import {panel, ping} from "./terminal-kit.js";
import {hit} from "./terminal-live.js";

const TFS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];
const SHORT = {"1m": "1분", "5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일"};
const LEVEL_TFS = ["15m", "30m", "1h", "4h"];
const MAIN = new Set(["core", "m5", "extra"]);
const TF_S = Object.fromEntries(Object.entries(bars.TF_MS).map(([k, v]) => [k, v / 1000]));
const RELAY_FRESH_MS = 6000;     // the forming bar keeps the relay's trade price this long against the 5 s candle poll

/** termChart(ctx, st, onTf) -> {el, ready, setSym, onTicker, onBoard, onTrades, tick} */
export function termChart(ctx, st, onTf) {
  const tfBtns = new Map();
  const tfBar = h("div", {class: "term-tfs", role: "tablist", "aria-label": "봉"}, TFS.map((tf) => {
    const b = h("button", {type: "button", role: "tab", "aria-selected": String(tf === st.tf), onclick: () => setTf(tf)}, SHORT[tf]);
    tfBtns.set(tf, b);
    return b;
  }));
  const legend = h("div", {class: "term-legend num"});
  const box = h("div", {class: "term-cbox"});
  const tag = h("div", {class: "term-ptag", hidden: true}, h("b", {class: "num"}, "—"), h("small", {class: "num"}, "—"));
  const dot = h("i", {class: "term-dot", hidden: true, "aria-hidden": "true"});
  const tip = h("div", {class: "term-tip", hidden: true, role: "tooltip"});
  const glows = h("div", {class: "term-glows", "aria-hidden": "true"});
  const wrap = h("div", {class: "term-cwrap"}, box, glows, legend, dot, tag, tip);
  const keyLine = h("div", {class: "term-ckey"});
  if (!TFS.includes(st.tf)) st.tf = "15m";
  const el = panel("차트", {cls: "term-chart", acts: [tfBar, h("a", {class: "term-more", href: ctx.href("chart", st.sym, {tf: st.tf})}, "차트 화면 →")]}, wrap, keyLine);
  const moreA = el.head.querySelector(".term-more");

  let C = null, series = null, last = null, t0 = 0, loadTok = 0, events = null, levels = null, trades = [], board = null, lastPx = null, relayAt = 0;
  let glowSeen = false;          // the first lines drawn for a coin are the baseline: their glows appear without motion
  const lines = {pos: new Map(), lv: [], glow: new Map()};
  const rm = (l) => { try { series.removePriceLine(l); } catch (e) { /* gone */ } };
  const dropGlow = (k) => { const g = lines.glow.get(k); if (g) { g.el.remove(); lines.glow.delete(k); } };

  function paintLegend(d) {
    if (!d) { legend.textContent = ""; return; }
    const ch = d.open ? (d.close - d.open) / d.open : null;
    put(legend, h("b", null, `${fmt.coin(st.sym)} · ${SHORT[st.tf]}`), ` 시 ${fmt.price(d.open)} 고 ${fmt.price(d.high)} 저 ${fmt.price(d.low)} 종 ${fmt.price(d.close)} `,
      h("span", {class: fmt.tone(ch)}, fmt.pct(ch, 2)));
  }

  // ---------------------------------------------------------------- overlays: the price tag + countdown, the dot, line glows
  /** Each entry / stop glow sits on its line's price; a line scrolled out of the price range hides its glow. */
  function placeGlows() {
    if (!lines.glow.size) return;
    let sw;
    try { sw = C.chart.priceScale("right").width(); } catch (e) { return; }       // the chart is mid-layout: next place()
    const W = Math.max(0, box.clientWidth - sw), H = box.clientHeight - 26;
    for (const g of lines.glow.values()) {
      const y = series.priceToCoordinate(g.price);
      if (y == null || y < 0 || y > H) { g.el.hidden = true; continue; }
      g.el.hidden = false;
      g.el.style.width = W + "px";
      g.el.style.transform = `translateY(${Math.round(y)}px)`;
    }
  }
  function place() {
    glows.hidden = !series || !last;
    if (!series || !last) { tag.hidden = true; dot.hidden = true; return; }
    placeGlows();
    const y = series.priceToCoordinate(last.close);
    const x = C.chart.timeScale().timeToCoordinate(last.time);
    const sw = C.chart.priceScale("right").width();
    const H = box.clientHeight - 26;
    if (y == null || y < 0 || y > H) { tag.hidden = true; } else {
      tag.hidden = false;
      tag.style.transform = `translateY(${Math.round(y - 11)}px)`;
      tag.style.width = sw + "px";
    }
    if (x == null || y == null || x < 0 || x > box.clientWidth - sw || y < 0 || y > H) dot.hidden = true;
    else { dot.hidden = false; dot.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`; }
    dot.classList.toggle("on", stream.live());
  }
  function paintTag(isLive) {
    if (!last) return;
    const b = tag.firstChild;
    const up = last.close >= last.open;
    tag.classList.toggle("up", up); tag.classList.toggle("down", !up);
    b.textContent = fmt.price(last.close);
    if (isLive && lastPx != null && last.close !== lastPx) motion.flashPrice(tag, last.close > lastPx ? "up" : "down");
    tag.lastChild.textContent = bars.closeIn(st.tf, serverNow());
    lastPx = last.close;
  }

  // ---------------------------------------------------------------- data
  async function loadCandles() {
    if (!series) return;
    const tk = ++loadTok, sym = st.sym, tf = st.tf;
    let data = [];
    try { data = await ctx.api(`/api/candles?symbol=${sym}&interval=${tf}&limit=500`); }
    catch (e) { if (e && e.name === "AbortError") return; ctx.toast("가격 자료를 불러오지 못했습니다"); }
    if (tk !== loadTok || !ctx.alive()) return;
    const dec = priceDec(data.length ? data[data.length - 1].close : store.mark(sym));
    series.applyOptions({priceFormat: {type: "price", precision: dec, minMove: Math.pow(10, -dec)}});
    series.setData(data);
    t0 = data.length ? data[0].time : 0;
    last = data[data.length - 1] || null;
    lastPx = null;
    paintLegend(last); paintTag(false);
    C.chart.timeScale().fitContent();
    C.chart.timeScale().scrollToPosition(6, false);
    drawPos(); loadTrades(); loadLevels(); drawMarks();
    requestAnimationFrame(place);
  }
  async function liveBar() {
    if (!series || !last) return;
    const sym = st.sym, tf = st.tf;
    try {
      const rows = await ctx.api(`/api/candles?symbol=${sym}&interval=${tf}&limit=2`);
      if (sym !== st.sym || tf !== st.tf) return;
      const before = last.close;
      for (let c of rows) {
        if (c.time < last.time) continue;
        // the relay's trade price of this bar is newer than the server's 4 s candle cache: keep it, take the wider range
        if (c.time === last.time && Date.now() - relayAt < RELAY_FRESH_MS) c = {...c, close: last.close, high: Math.max(c.high, last.high), low: Math.min(c.low, last.low)};
        try { series.update(c); last = c; } catch (e) { /* older bar */ }
      }
      paintLegend(last); paintTag(true); place();
      if (last.close !== before) ping(el);
    } catch (e) { /* next poll */ }
  }
  async function eventsList() {
    if (events && Date.now() - events.at < 600000) return events.list;
    try { const d = await ctx.api("/api/events?days_back=60&days_ahead=1"); events = {at: Date.now(), list: d.events || []}; }
    catch (e) { events = {at: Date.now(), list: []}; }
    return events.list;
  }
  async function loadTrades() {
    const sym = st.sym;
    try { const rows = await ctx.api(`/api/trades?symbol=${encodeURIComponent(sym)}&limit=100`); if (sym === st.sym && ctx.alive()) { trades = rows || []; drawMarks(); } }
    catch (e) { /* marks stay */ }
  }
  async function loadLevels() {
    const sym = st.sym, tf = st.tf;
    let lv = null;
    if (LEVEL_TFS.includes(tf)) { try { lv = await ctx.api(`/api/levels?symbol=${sym}&tf=${tf}`); } catch (e) { lv = null; } }
    if (sym !== st.sym || tf !== st.tf || !ctx.alive()) return;
    levels = lv; drawLevels();
  }

  // ---------------------------------------------------------------- marks and lines
  const groupOfT = (t) => fmt.SERVER_GROUP[t.group] || fmt.groupOf({kind: t.kind, timeframe: t.timeframe});
  let evBars = new Map();
  async function drawMarks() {
    if (!series) return;
    const sym = st.sym, tf = st.tf, step = TF_S[tf] || 900;
    const marks = [];
    evBars = new Map();
    if (step < 86400) {
      const now = serverNow() / 1000;
      for (const e of await eventsList()) {
        const s = Math.floor(e.ts_ms / 1000);
        if (s < t0 || s > now) continue;
        const bt = s - (s % step);
        evBars.set(bt, [...(evBars.get(bt) || []), e]);
        marks.push({time: bt, position: "aboveBar", color: tok("--warn"), shape: "square", text: e.kind});
      }
    }
    const mine = trades.filter((t) => t.symbol === sym && MAIN.has(groupOfT(t)) && t.entry_time / 1000 >= t0).slice(0, 12);
    for (const t of mine) {
      const e = Math.floor(t.entry_time / 1000), x = Math.floor(t.exit_time / 1000);
      marks.push({time: e - (e % step), position: t.side > 0 ? "belowBar" : "aboveBar", color: tok("--accent"), shape: t.side > 0 ? "arrowUp" : "arrowDown", text: ""});
      marks.push({time: x - (x % step), position: t.side > 0 ? "aboveBar" : "belowBar", color: t.pnl > 0 ? tok("--up") : tok("--down"), shape: "circle", text: ""});
    }
    if (sym !== st.sym || tf !== st.tf) return;
    marks.sort((a, b) => a.time - b.time);
    series.setMarkers(marks);
    put(keyLine, h("span", null, h("i", {class: "k-ar"}), "우리 진입"), h("span", null, h("i", {class: "k-up"}), "청산 이익"), h("span", null, h("i", {class: "k-dn"}), "청산 손실"),
      h("span", null, h("i", {class: "k-ev"}), "경제지표 (올리면 이름)"), h("span", null, h("i", {class: "k-ln"}), "진입선·손절선 (기존 36·5분봉·추가)"),
      LEVEL_TFS.includes(st.tf) ? h("span", null, h("i", {class: "k-sr"}), "지지·저항") : null);
  }
  function drawPos() {
    if (!series) return;
    const list = board ? board.accounts.filter((a) => a.position && a.position.symbol === st.sym && MAIN.has(fmt.groupOf(a)))
      .map((a) => ({a, p: normPos(a.position)})).sort((x, y) => x.p.entry - y.p.entry) : [];
    const groups = [];
    for (const x of list) {
      const g = groups[groups.length - 1];
      if (g && Math.abs(x.p.entry - g.price) / g.price < 0.0005) g.items.push(x); else groups.push({price: x.p.entry, items: [x]});
    }
    const m = store.mark(st.sym), want = new Map();
    for (const g of groups) {
      const pnl = m ? g.items.reduce((s, x) => s + x.p.side * x.p.qty * (m - x.p.entry), 0) : null;
      const mg = g.items.reduce((s, x) => s + (x.p.margin || 0), 0);
      const L = g.items.filter((x) => x.p.side > 0).length, S = g.items.length - L;
      const title = g.items.length === 1 ? `${fmt.sideKo(g.items[0].p.side)} ${fmt.lev(g.items[0].p.leverage)}${pnl != null ? " " + fmt.pct(pnl / mg, 1) : ""}`
        : `${g.items.length}개 ${L ? "롱" + L : ""}${L && S ? "·" : ""}${S ? "숏" + S : ""}${pnl != null && mg ? " " + fmt.pct(pnl / mg, 1) : ""}`;
      const tone = pnl == null ? "flat" : pnl >= 0 ? "up" : "down";
      want.set("e" + g.items.map((x) => x.a.account_id).join(",") + "@" + g.price, {price: g.price, color: tone === "flat" ? tok("--muted") : tok(tone === "up" ? "--up" : "--down"), title, w: 2, style: 0, tone});
    }
    if (list.length <= 4) {
      for (const x of list) if (x.p.stop) {
        const lock = x.p.lock_roe != null && !fmt.ownExits(x.a);
        want.set("s" + x.a.account_id + "@" + x.p.stop, {price: x.p.stop, color: lock ? tok("--up") : tok("--down"), w: 1, style: 2,
          title: lock ? `잠금 +${fmt.num(x.p.lock_roe * 100, 0)}%` : "손절", tone: lock ? "up" : "down"});
      }
    }
    for (const [k, l] of lines.pos) if (!want.has(k)) { rm(l); lines.pos.delete(k); dropGlow(k); }
    for (const [k, w] of want) {
      const o = {price: w.price, color: w.color, lineWidth: w.w, lineStyle: w.style, axisLabelVisible: true, title: w.title};
      if (lines.pos.has(k)) lines.pos.get(k).applyOptions(o); else lines.pos.set(k, series.createPriceLine(o));
      let g = lines.glow.get(k);
      if (!g) {
        const band = h("i");
        g = {price: w.price, el: h("span", {class: "term-glow", hidden: true, dataset: {k: k[0] === "e" ? "entry" : "stop"}}, band), band, fresh: true};
        lines.glow.set(k, g);
        glows.append(g.el);
      }
      g.el.dataset.tone = w.tone;
    }
    if (series && last) placeGlows();
    const real = glowSeen;
    if (board) glowSeen = true;
    for (const g of lines.glow.values()) if (g.fresh) { g.fresh = false; if (real && !g.el.hidden) motion.drawIn(g.band, 500); }
  }
  function drawLevels() {
    if (!series) return;
    lines.lv.forEach(rm); lines.lv = [];
    if (!levels || !levels.levels) return;
    for (const side of ["resistance", "support"]) {
      levels.levels.filter((x) => x.side === side && (x.atr == null || Math.abs(x.atr) <= 8)).slice(0, 2).forEach((x) => lines.lv.push(series.createPriceLine({
        price: x.price, color: side === "resistance" ? tok("--down-line") : tok("--up-line"), lineWidth: 1, lineStyle: 1, axisLabelVisible: false,
        title: side === "resistance" ? "저항" : "지지"})));
    }
  }

  // ---------------------------------------------------------------- changes
  function setTf(tf) {
    if (tf === st.tf || !TFS.includes(tf)) return;
    onTf(tf);
    for (const [k, b] of tfBtns) b.setAttribute("aria-selected", String(k === tf));
    moreA.href = ctx.href("chart", st.sym, {tf});
    loadCandles();
  }

  const ready = (async () => {
    try {
      C = await makeChart(box, {rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.08, bottom: 0.08}},
        timeScale: {rightOffset: 6}, grid: {vertLines: {color: tok("--line")}, horzLines: {color: tok("--line")}}});
      ctx.track(C.dispose);
      series = C.chart.addCandlestickSeries({...candleOptions(), lastValueVisible: false, priceLineVisible: true, priceLineStyle: 2, priceLineWidth: 1,
        priceLineColor: tok("--accent")});
      C.chart.subscribeCrosshairMove((p) => {
        const d = p && p.seriesData && p.seriesData.get(series);
        paintLegend(d || last);
        const evs = p && p.time != null ? evBars.get(p.time) : null;
        if (!evs || !p.point) { tip.hidden = true; return; }
        put(tip, evs.map((e) => h("div", null, h("b", null, e.name_ko || e.kind), h("span", {class: "num"}, ` ${fmt.kst(e.ts_ms)} (한국)`))));
        tip.hidden = false;
        tip.style.transform = `translate(${Math.min(Math.max(8, p.point.x + 12), box.clientWidth - 220)}px, ${Math.max(8, p.point.y - 40)}px)`;
      });
      C.chart.timeScale().subscribeVisibleLogicalRangeChange(() => requestAnimationFrame(place));
      if (typeof ResizeObserver === "function") { const ro = new ResizeObserver(() => requestAnimationFrame(place)); ro.observe(box); ctx.track(() => ro.disconnect()); }
    } catch (e) {
      put(box, h("div", {class: "term-cfail"}, ui.errorBox(e, () => location.reload())));
      return;
    }
    await loadCandles();
  })();

  ctx.every(5000, liveBar, {now: false});
  ctx.every(120000, loadLevels, {now: false});
  return {
    el, ready,
    setSym() { relayAt = 0; lines.pos.forEach(rm); lines.pos.clear(); [...lines.glow.keys()].forEach(dropGlow); glowSeen = false; trades = []; moreA.href = ctx.href("chart", st.sym, {tf: st.tf}); loadCandles(); },
    onTicker() { drawPos(); },
    onBoard(b) { board = b; drawPos(); },
    onTrades(rows) { if ((rows || []).some((t) => t.symbol === st.sym)) loadTrades(); },
    /** A real relay event of the selected coin {s, side, p, t}: the forming candle takes that trade's price (only a
     *  trade inside the bar on screen; the next bar comes with the 5 s poll) and the price tag lights once. */
    onTick(ev) {
      const p = Number(ev.p), t = Number(ev.t) / 1000, span = TF_S[st.tf];
      if (ev.s !== st.sym || !series || !last || !Number.isFinite(p) || p <= 0 || !span) return;
      if (!(t >= last.time && t < last.time + span)) return;
      const prev = last.close, c = {...last, close: p, high: Math.max(last.high, p), low: Math.min(last.low, p)};
      try { series.update(c); } catch (e) { return; }
      last = c; relayAt = Date.now();
      paintLegend(last); paintTag(false); place();
      hit(tag, p > prev ? "up" : p < prev ? "down" : ev.side === "buy" ? "up" : "down");
      ping(el);
    },
    tick() {
      if (!last) return;
      tag.lastChild.textContent = bars.closeIn(st.tf, serverNow());
      place();
    },
  };
}

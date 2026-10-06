// 터미널 centre: the candle chart with the same engine and helpers as 차트 (core/lwc makeChart / candleOptions / tok /
// priceDec, positions-kit normPos): /api/candles (500 bars, then the forming bar every 5 s like 차트), our open positions
// on this coin as entry lines (기존 36 · 5분봉 · 추가 계좌) with their nearest stops / locks, our recent closed trades as
// entry / exit marks, support / resistance (/api/levels, the four house timeframes), US macro releases as marks with a
// tooltip, and the price tag on the right axis: the last price, dashed across the chart, with the bar-close countdown
// under it; it glows teal / pink when the server's price really moved. A small dot breathes on the last candle while the
// stream is live (never while the page is hidden or under reduced motion).
// The chart deck (core/chartfx.js, owners 10/06 "간지나게 · 선은 얇게 · 누르면 숨기게"): in the AI skin the candles
// glow, the pane carries the Premium (red, above) / Discount (sky blue, below) light and flashes once on a real big trade / liquidation / our fill of
// this coin; our lines are 1 px with a compact pill at the left (click to hide), never in the autoscale, an edge
// marker when off the price range; the '선' menu, 프리미엄 지표 (core/smc.js) and the volume bars along the bottom.
import {h, put, ui, fmt, store, motion, bars, serverNow, stream, makeChart, candleOptions, tok, priceDec, chartDeck,
  bigEvent, liqEvent, ownEvent} from "../core/pb.js";
import {panel, ping} from "./terminal-kit.js";
import {hit} from "./terminal-live.js";
import {posLines} from "./chart-lines.js";
import {drawTools} from "./draw-kit.js";

const TFS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];
const SHORT = {"1m": "1분", "5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일"};
const LEVEL_TFS = ["15m", "30m", "1h", "4h"];
const MAIN = new Set(["core", "m5", "extra"]);
const TF_S = Object.fromEntries(Object.entries(bars.TF_MS).map(([k, v]) => [k, v / 1000]));
const RELAY_FRESH_MS = 6000;
const narrowBox = () => typeof matchMedia === "function" && matchMedia("(max-width: 1279px)").matches;     // the forming bar keeps the relay's trade price this long against the 5 s candle poll

/** termChart(ctx, st, onTf) -> {el, ready, setSym, onTicker, onBoard, onTrades, onTick, flash, tick} */
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
  const wrap = h("div", {class: "term-cwrap"}, box, legend, dot, tag, tip);
  const keyLine = h("div", {class: "term-ckey"});
  const fxSlot = h("span", {class: "term-fx"});            // the deck's header controls (filled once the chart exists)
  if (!TFS.includes(st.tf)) st.tf = "15m";
  const el = panel("차트", {cls: "term-chart", acts: [fxSlot, tfBar, h("a", {class: "term-more", href: ctx.href("chart", st.sym, {tf: st.tf})}, "차트 화면 →")]}, wrap, keyLine);
  const moreA = el.head.querySelector(".term-more");

  let C = null, series = null, deck = null, last = null, t0 = 0, loadTok = 0, events = null, levels = null, trades = [], board = null, lastPx = null, relayAt = 0;
  let seenPos = null;            // this coin's open positions at the last board (a new one is a real fill: one accent flash)
  let draw = null, alerts = null;  // conv-b: the drawing tools (draw-kit.js) and the last /api/price-alerts answer

  // the armed price alerts of this coin as the deck's '가격 알림 선' (the same lines as the 차트 screen's; group "al" is not
  // in this deck's '선' menu, so they always show: a fired or deleted alert leaves with the next answer)
  function drawAlerts() {
    if (!deck) return;
    deck.setLines("al", ((alerts && alerts.alerts) || []).filter((a) => a.symbol === st.sym && a.armed).map((a) => ({
      id: `al:${a.id ?? a.price}`, group: "al", price: a.price, tone: "accent", dash: 2, alpha: 0.6, axis: true, glow: false,
      label: `알림 ${a.direction === "above" ? "↑" : "↓"}`})));
  }
  async function loadAlerts() {
    try { alerts = await ctx.api("/api/price-alerts"); } catch (e) { return; }
    if (ctx.alive()) drawAlerts();
  }

  function paintLegend(d) {
    if (!d) { legend.textContent = ""; return; }
    const ch = d.open ? (d.close - d.open) / d.open : null;
    put(legend, h("b", null, `${fmt.coin(st.sym)} · ${SHORT[st.tf]}`), ` 시 ${fmt.price(d.open)} 고 ${fmt.price(d.high)} 저 ${fmt.price(d.low)} 종 ${fmt.price(d.close)} `,
      h("span", {class: fmt.tone(ch)}, fmt.pct(ch, 2)));
  }

  // ---------------------------------------------------------------- overlays: the price tag + countdown, the dot
  function place() {
    if (!series || !last) { tag.hidden = true; dot.hidden = true; return; }
    const y = series.priceToCoordinate(last.close);
    const x = C.chart.timeScale().timeToCoordinate(last.time);
    let sw, th;
    try { sw = C.chart.priceScale("right").width(); th = C.chart.timeScale().height(); } catch (e) { return; }   // mid-layout
    const H = box.clientHeight - th;
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
    deck.setData(data);
    if (draw) draw.setKey();                 // this coin + timeframe's own drawings
    drawAlerts();
    t0 = data.length ? data[0].time : 0;
    last = data[data.length - 1] || null;
    lastPx = null;
    paintLegend(last); paintTag(false);
    deck.showRecent(narrowBox() ? 120 : 220, narrowBox() ? 12 : 26);
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
        if (deck.update(c)) last = c;
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
    if (step < 86400 && deck.shown("ev")) {
      const now = serverNow() / 1000;
      for (const e of await eventsList()) {
        const s = Math.floor(e.ts_ms / 1000);
        if (s < t0 || s > now) continue;
        const bt = s - (s % step);
        evBars.set(bt, [...(evBars.get(bt) || []), e]);
        marks.push({time: bt, position: "aboveBar", color: tok("--warn"), shape: "square", text: e.kind, glow: false});
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
    deck.setMarkers(marks);
    put(keyLine, h("span", null, h("i", {class: "k-ar"}), "우리 진입"), h("span", null, h("i", {class: "k-up"}), "청산 이익"), h("span", null, h("i", {class: "k-dn"}), "청산 손실"),
      h("span", null, h("i", {class: "k-ev"}), "경제지표 (올리면 이름)"), h("span", null, h("i", {class: "k-ln"}), "진입선·손절선 (기존 36·5분봉·추가) · 이름표를 누르면 숨김"),
      LEVEL_TFS.includes(st.tf) ? h("span", null, h("i", {class: "k-sr"}), "지지·저항") : null,
      h("span", {title: "차트에서 오른쪽 클릭: 이 가격에 텔레그램 알림 걸기 · 가로선 긋기 (그리기 버튼: 선·네모·글)"}, "오른쪽 클릭 = 이 가격에 알림"));
  }
  function drawPos() {
    if (!deck) return;
    const accts = board ? board.accounts.filter((a) => a.position && a.position.symbol === st.sym && MAIN.has(fmt.groupOf(a))) : [];
    deck.setLines("pos", posLines(accts, store.mark(st.sym), {stops: 6}));
    // a position of this coin that is new since the last board: our bot really filled an entry (one accent flash)
    const now = new Set(accts.map((a) => a.account_id + "@" + (a.position.entry_time || a.position.entry_price || a.position.entry)));
    if (seenPos && [...now].some((k) => !seenPos.has(k))) deck.flash(ownEvent());
    if (board) seenPos = now;
  }
  function drawLevels() {
    if (!deck) return;
    const out = [];
    for (const side of ["resistance", "support"]) {
      ((levels && levels.levels) || []).filter((x) => x.side === side && (x.atr == null || Math.abs(x.atr) <= 8)).slice(0, 2).forEach((x, i) => out.push({
        id: `lv:${side}:${i}`, group: "sr", price: x.price, tone: side === "resistance" ? "down" : "up", dash: 2, alpha: 0.45, axis: false, glow: false,
        label: side === "resistance" ? "저항" : "지지"}));
    }
    deck.setLines("sr", out);
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
        timeScale: {rightOffset: 26}, grid: {vertLines: {color: tok("--line")}, horzLines: {color: tok("--line")}}});
      ctx.track(C.dispose);
      series = C.chart.addCandlestickSeries({...candleOptions(), lastValueVisible: false, priceLineVisible: true, priceLineStyle: 2, priceLineWidth: 1,
        priceLineColor: tok("--accent")});
      deck = chartDeck({chart: C.chart, series, wrap, box, ctx, key: "term", groups: ["pos", "risk", "sr", "smc", "ev", "vol"]});
      deck.onToggle((g) => { if (g === "ev" || g == null) drawMarks(); });
      // conv-b: 그리기 (lines, boxes, notes per coin + timeframe on this device) and the right-click '이 가격에 알림'
      // (the existing /api/price-alerts route); the armed alerts of this coin are the deck's '가격 알림 선'
      draw = drawTools({ctx, chart: C.chart, series, wrap, box, deck, sym: () => st.sym, tf: () => st.tf, step: () => TF_S[st.tf] || 900,
        onAlertAdded: () => loadAlerts()});
      put(fxSlot, deck.lightChip, deck.flashSel, deck.smcBtn, deck.menuBtn, draw.toggle);
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
  ctx.every(30000, loadAlerts, {now: true});           // conv-b: the armed alerts (a fired one leaves the chart)
  return {
    el, ready,
    setSym() { relayAt = 0; seenPos = null; if (deck) { deck.setLines("pos", []); deck.setLines("sr", []); } trades = []; moreA.href = ctx.href("chart", st.sym, {tf: st.tf}); loadCandles(); },
    onTicker() { drawPos(); },
    onBoard(b) { board = b; drawPos(); },
    onTrades(rows) {
      if (!(rows || []).some((t) => t.symbol === st.sym)) return;
      loadTrades();
      if (deck && (rows || []).some((t) => t.symbol === st.sym && MAIN.has(groupOfT(t)))) deck.flash(ownEvent());   // our real exit fill
    },
    /** A real relay event of the selected coin {s, side, p, t}: the forming candle takes that trade's price (only a
     *  trade inside the bar on screen; the next bar comes with the 5 s poll) and the price tag lights once. */
    onTick(ev) {
      const p = Number(ev.p), t = Number(ev.t) / 1000, span = TF_S[st.tf];
      if (ev.s !== st.sym || !series || !last || !Number.isFinite(p) || p <= 0 || !span) return;
      if (!(t >= last.time && t < last.time + span)) return;
      const prev = last.close, c = {...last, close: p, high: Math.max(last.high, p), low: Math.min(last.low, p)};
      if (!deck.update(c)) return;
      last = c; relayAt = Date.now();
      paintLegend(last); paintTag(false); place();
      hit(tag, p > prev ? "up" : p < prev ? "down" : ev.side === "buy" ? "up" : "down");
      ping(el);
    },
    /** A real market event of the selected coin: a new big taker trade (relay row) or a new market liquidation. */
    onBig(r) { if (deck && r && r.s === st.sym) deck.flash(bigEvent(r)); },
    onLiq(r) { if (deck && r) deck.flash(liqEvent(r)); },
    tick() {
      if (!last) return;
      tag.lastChild.textContent = bars.closeIn(st.tf, serverNow());
      place();
    },
  };
}

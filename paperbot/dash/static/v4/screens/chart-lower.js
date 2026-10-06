// 차트 아래 칸 (chart-plus, addition 12): up to two small charts under the candles, on the candles' own time axis.
//   cvd   사고파는 힘: buy minus sell volume per bar from the candles' taker-buy volume (/api/candles taker_buy, kline
//         field 9), summed over the bars on screen (zero at the left edge) + the per-bar buy / sell bars. A calculation
//         from bar data, said so in its header: 봉 자료로 계산한 근사치 (the exchange's own tick-level CVD is not this).
//   oi    미결제약정: Binance's open interest history in USDT (the server fetches it: /api/v4/chartplus/series)
//   fund  펀딩비: the rates Binance settled (every 8 hours), summed inside each bar, no bar where none was settled
//   ls    롱/숏 비율: the global long / short ACCOUNT ratio, a 1.0 line (above 1: more long accounts)
// Each pane is its own lightweight-charts chart (v4 has no panes) whose visible range follows the main chart's (same
// logical indexes: every pane series has one point per candle, an empty one where there is no value), whose price
// scale is as wide as the main one (so the plot areas line up) and whose crosshair follows the main crosshair.
// HONESTY: a series that cannot be loaded draws NOTHING (its own 못 불러옴 note and a retry), never a flat line or a zero;
// a bar without a value is a gap; a stale answer says so; Binance's 30-day limit says so.
import {h, fmt, makeChart, tok} from "../core/pb.js";
import {TF_S, cvd, alignSeries, alignFunding} from "./chart-plus-calc.js";
import {koUsd, koUsdt, palette} from "./chart-plus-kit.js";

export const PANES = {
  cvd: {ko: "CVD · 사고파는 힘", plain: "오르면 시장가로 사는 쪽이 더 많음", note: "봉 자료로 계산한 근사치"},
  oi: {ko: "미결제약정", plain: "아직 열려 있는 계약의 총액 (USDT)", note: "바이낸스 전체"},
  fund: {ko: "펀딩비", plain: "플러스면 롱이 숏에게 냄 (8시간마다)", note: "바이낸스가 정산한 값"},
  ls: {ko: "롱/숏 비율", plain: "1보다 크면 롱 계좌가 더 많음", note: "전체 계좌"},
};
const KIND_OF = {oi: "oi", fund: "funding", ls: "ls"};
const FUND_WARN = 0.0005;             // a bar's summed funding beyond +-0.05 % gets the attention colour (below it: neutral, no 'loss' colour)

/**
 * lowerPanes({ctx, chart, series, deck, host, sym, tf, onClose, report}) -> {set(ids), onData(how), reload(), view()}
 *   host: the element the panes are added to (in order); onClose(id): the pane's × (the owner turns it off)
 */
export function lowerPanes(o) {
  const {ctx, chart, deck, host} = o;
  const panes = new Map();                // id -> pane
  let want = [], relaying = 0, cvdTimer = 0, barTimer = 0;

  const ts = () => chart.timeScale();
  const mainW = () => { try { return chart.priceScale("right").width(); } catch (e) { return 0; } };
  const candles = () => deck.data();
  const visRange = () => {
    const r = ts().getVisibleLogicalRange(), n = candles().length;
    return r ? {a: Math.max(0, Math.ceil(r.from)), z: Math.min(n - 1, Math.floor(r.to))} : {a: 0, z: n - 1};
  };
  const decFor = (v) => { const a = Math.abs(v); return a >= 1000 ? 0 : a >= 100 ? 1 : a >= 1 ? 2 : 3; };

  // ---------------------------------------------------------------- building a pane
  async function build(id) {
    const def = PANES[id];
    const p = {id, def, el: null, C: null, S: {}, data: null, err: null, busy: false, vals: new Map(), built: false, gone: false, last: null};
    panes.set(id, p);
    const title = h("b", {class: "cfxp-pt"}, def.ko);
    const plain = h("span", {class: "cfxp-pp", title: `${def.plain} · ${def.note}`}, `${def.plain} · ${def.note}`);
    const chip = h("span", {class: "cfxp-chip", hidden: true});
    const retry = h("button", {type: "button", class: "cfxp-retry", hidden: true, onclick: () => load(p, true)}, "다시 시도");
    const val = h("span", {class: "cfxp-pv num"}, "—");
    const close = h("button", {type: "button", class: "cfxp-x", "aria-label": `${def.ko} 칸 닫기`, title: "이 칸 닫기", onclick: () => o.onClose && o.onClose(id)}, "×");
    const head = h("div", {class: "cfxp-ph"}, title, plain, chip, retry, h("span", {class: "cfxp-grow"}), val, close);
    const boxEl = h("div", {class: "cfxp-pbox"});
    const msg = h("div", {class: "cfxp-pmsg", hidden: true});
    p.el = h("section", {class: "cfxp-pane", dataset: {id}, "aria-label": def.ko}, boxEl, head, msg);
    p.ui = {chip, retry, val, msg, plain};
    host.append(p.el);
    sortHost();
    const pal = palette();
    try {
      p.C = await makeChart(boxEl, {
        rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.34, bottom: 0.06}, minimumWidth: mainW()},
        timeScale: {visible: false, rightOffset: 26},
        handleScroll: false, handleScale: false,
        crosshair: {mode: 0, horzLine: {visible: false, labelVisible: false}},
        grid: {vertLines: {color: tok("--line")}, horzLines: {color: tok("--line")}},
        layout: {background: {color: tok("--surface")}, attributionLogo: false},        // (the main chart above carries the attribution)
        localization: {priceFormatter: (v) => priceFmt(id, v)},
      });
    } catch (e) {
      p.err = e; p.built = true;
      fail(p, "차트 라이브러리를 못 불러옴");
      return;
    }
    if (p.gone) { p.C.dispose(); return; }
    const c = p.C.chart;
    if (id === "cvd") {
      p.S.line = c.addLineSeries({color: pal.accent, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: true});
      p.S.hist = c.addHistogramSeries({priceScaleId: "delta", priceLineVisible: false, lastValueVisible: false, priceFormat: {type: "volume"}});
      c.priceScale("delta").applyOptions({scaleMargins: {top: 0.74, bottom: 0}, visible: false});
      c.priceScale("right").applyOptions({scaleMargins: {top: 0.34, bottom: 0.3}});
    } else if (id === "oi") {
      p.S.line = c.addAreaSeries({lineColor: pal.accent, topColor: tok("--accent-soft") || "transparent", bottomColor: "transparent", lineWidth: 2,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: true});
    } else if (id === "ls") {
      p.S.line = c.addLineSeries({color: pal.accent, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: true});
      p.S.base = p.S.line.createPriceLine({price: 1, color: pal.muted, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: ""});
    } else {
      p.S.hist = c.addHistogramSeries({priceLineVisible: false, lastValueVisible: false});
    }
    p.built = true;
    host.style.setProperty("--cfxp-axw", (mainW() + 4) + "px");
    c.subscribeCrosshairMove((q) => paneMove(p, q));
    apply(p);
    load(p, false);
  }
  function priceFmt(id, v) {
    if (id === "oi") return koUsd(v);
    if (id === "fund") return fmt.pct(v, 3);
    if (id === "ls") return fmt.num(v, 2);
    return fmt.num(v, decFor(v));
  }
  function sortHost() {
    for (const id of want) { const p = panes.get(id); if (p && p.el && p.el.parentElement === host) host.append(p.el); }
  }

  // ---------------------------------------------------------------- data
  async function load(p, force) {
    const kind = KIND_OF[p.id];
    if (!kind || p.busy || p.gone) return;
    const sym = o.sym(), tf = o.tf();
    p.busy = true;
    let r = null, e = null;
    try { r = await ctx.api(`/api/v4/chartplus/series?symbol=${encodeURIComponent(sym)}&kind=${kind}&tf=${tf}`); }
    catch (x) { e = x; }
    p.busy = false;
    if (p.gone || !ctx.alive()) return;
    if (sym !== o.sym() || tf !== o.tf()) { load(p, force); return; }
    if (e && e.name === "AbortError") return;
    if (r && r.ready) { p.data = r; p.err = null; }
    else if (r) { p.err = {message: r.why_ko || "바이낸스에서 못 불러옴"}; if (!p.data || p.data.symbol !== sym) p.data = null; }
    else { p.err = e || new Error("no answer"); if (p.data && p.data.symbol !== sym) p.data = null; }
    p.sym = sym; p.tf = tf;
    apply(p);
  }

  /** the pane's series from the candles (+ its fetched series), or an honest empty state */
  function apply(p) {
    if (!p.built || !p.C || p.gone) return;
    const cs = candles();
    const ui = p.ui;
    const times = cs.map((c) => c.time), step = TF_S[o.tf()] || 900;
    let line = null, hist = null, chip = "", why = "", can = true;
    p.vals = new Map();
    p.last = null;
    if (p.id === "cvd") {
      const {a, z} = visRange(), r = cvd(cs, a, z), pc = palette();
      if (cs.length && r.missing === cs.length) { can = false; why = "봉 자료에 매수 체결량이 없어 계산하지 못했습니다"; chip = "계산 못 함"; }
      else {
        line = cs.map((c, i) => (r.cum[i] == null ? {time: c.time} : {time: c.time, value: r.cum[i]}));
        hist = cs.map((c, i) => (r.delta[i] == null ? {time: c.time} : {time: c.time, value: r.delta[i], color: r.delta[i] >= 0 ? pc.up : pc.down}));
        cs.forEach((c, i) => { if (r.cum[i] != null) p.vals.set(c.time, {v: r.cum[i], d: r.delta[i]}); });
        if (r.missingVisible) chip = "일부 봉은 비워 둠";
      }
    } else if (!p.data) {
      can = false;
      why = p.err ? `${p.err.message || "바이낸스에서 못 불러옴"} · 30초마다 다시 받아 봅니다` : "불러오는 중…";
      chip = p.err ? "못 불러옴" : "";
    } else {
      const d = p.data;
      if (p.id === "fund") {
        const al = alignFunding(d.points, times, step), pal = palette();
        hist = cs.map((c, i) => (al[i] ? {time: c.time, value: al[i].v, color: Math.abs(al[i].v) >= FUND_WARN ? pal.warn : pal.muted} : {time: c.time}));
        al.forEach((x, i) => { if (x) p.vals.set(cs[i].time, {v: x.v, n: x.n, ts: x.ts}); });
      } else {
        const al = alignSeries(d.points, times, step, d.period_s);
        line = cs.map((c, i) => (al[i] ? {time: c.time, value: al[i].v} : {time: c.time}));
        al.forEach((x, i) => { if (x) p.vals.set(cs[i].time, {v: x.v, x: x.x, ts: x.ts, carried: x.carried}); });
      }
      if (d.stale || p.err) chip = "마지막 값 (새로 못 받음)";                // the server's old answer, or this page's own failed refresh: never shown as fresh
      else if (cs.length && cs[0].time * 1000 < d.oldest - d.period_s * 1000 && p.id !== "fund") chip = "앞쪽은 바이낸스 자료 없음 (최근 30일)";
      else if (cs.length && cs[0].time * 1000 < d.oldest - 8 * 3600000 && p.id === "fund") chip = "앞쪽 정산은 받아 오지 않음 (최근 1000번)";
    }
    // never a flat line over a failure: the series are emptied
    const S = p.S;
    if (S.line) S.line.setData(can && line ? line : []);
    if (S.hist) S.hist.setData(can && hist ? hist : []);
    ui.chip.hidden = !chip; ui.chip.textContent = chip; ui.chip.dataset.tone = can ? "warn" : "bad";
    ui.retry.hidden = !(KIND_OF[p.id] && (p.err || (p.data && p.data.stale)));
    ui.msg.hidden = can; ui.msg.textContent = can ? "" : why;
    ui.plain.hidden = !can;
    p.can = can;
    for (let i = cs.length - 1; i >= 0; i--) if (p.vals.has(cs[i].time)) { p.last = cs[i].time; break; }
    paintVal(p, null);
    syncRange(p);
    if (o.report) o.report(view());
  }
  function paintVal(p, time) {
    const t = time != null && p.vals.has(time) ? time : p.last;
    const x = p.can && t != null ? p.vals.get(t) : null;
    const el = p.ui.val;
    if (!x) { el.textContent = p.can ? "—" : ""; return; }
    const hov = time != null && p.vals.has(time);
    const pre = hov ? fmt.kst(t * 1000) + " · " : "", asOf = !hov && x.ts ? ` · ${fmt.hm(x.ts)} 기준` : "";       // the last value says when Binance recorded it
    if (p.id === "cvd") el.textContent = `${pre}누적 ${fmt.num(x.v, decFor(x.v), true)} ${fmt.coin(o.sym())}`;
    else if (p.id === "oi") el.textContent = `${pre}${koUsdt(x.v)}${asOf}`;
    else if (p.id === "ls") el.textContent = `${pre}${fmt.num(x.v, 2)}${x.x != null ? ` (롱 ${fmt.pct(x.x, 0, false)})` : ""}${asOf}`;
    else el.textContent = `${pre}${fmt.pct(x.v, 4)}${x.n > 1 ? ` (${x.n}번 합)` : ""}${asOf}`;
  }
  function fail(p, why) {
    p.can = false;
    p.ui.msg.hidden = false; p.ui.msg.textContent = why;
    p.ui.chip.hidden = false; p.ui.chip.textContent = "못 불러옴"; p.ui.chip.dataset.tone = "bad";
    if (o.report) o.report(view());
  }

  // ---------------------------------------------------------------- the main chart drives the panes
  function syncRange(p) {
    if (!p.C || !p.built) return;
    const r = ts().getVisibleLogicalRange();
    if (r) { try { p.C.chart.timeScale().setVisibleLogicalRange(r); } catch (e) { /* mid-layout */ } }
  }
  let lastW = -1;
  ts().subscribeVisibleLogicalRangeChange((r) => {
    if (!panes.size) return;
    const w = mainW();
    host.style.setProperty("--cfxp-axw", (w + 4) + "px");
    for (const p of panes.values()) {
      if (!p.C || !p.built) continue;
      if (w !== lastW) p.C.chart.priceScale("right").applyOptions({minimumWidth: w});
      if (r) { try { p.C.chart.timeScale().setVisibleLogicalRange(r); } catch (e) { /* mid-layout */ } }
    }
    lastW = w;
    const cp = panes.get("cvd");                  // the sum starts at the left edge of the bars on screen: again when that moves
    if (cp && cp.built && !cvdTimer) cvdTimer = setTimeout(() => { cvdTimer = 0; const q = panes.get("cvd"); if (q) apply(q); }, 140);
  });
  ctx.track(() => { if (cvdTimer) clearTimeout(cvdTimer); if (barTimer) clearTimeout(barTimer); });
  // the crosshair of the main chart shows in every pane, and the pane's header value follows it
  chart.subscribeCrosshairMove((q) => {
    if (relaying || !panes.size) return;
    relaying++;
    try {
      const t = q && q.time != null ? q.time : null;
      for (const p of panes.values()) {
        if (!p.C || !p.built) continue;
        paintVal(p, t);
        const x = t != null ? p.vals.get(t) : null;
        const s = p.S.line || p.S.hist;
        try { if (x && s && p.can) p.C.chart.setCrosshairPosition(x.v, t, s); else p.C.chart.clearCrosshairPosition(); } catch (e) { /* older build */ }
      }
    } finally { relaying--; }
  });
  function paneMove(p, q) {
    if (relaying) return;
    relaying++;
    try {
      const t = q && q.time != null ? q.time : null;
      paintVal(p, t);
      const cs = candles(), c = t != null ? cs.find((x) => x.time === t) : null;
      try { if (c && p.can) chart.setCrosshairPosition(c.close, t, o.series); else chart.clearCrosshairPosition(); } catch (e) { /* older build */ }
      for (const q2 of panes.values()) if (q2 !== p && q2.C && q2.built) paintVal(q2, t);
    } finally { relaying--; }
  }

  // ---------------------------------------------------------------- the owner
  ctx.every(30000, () => { for (const p of panes.values()) if (KIND_OF[p.id] && p.built) load(p, false); }, {now: false});
  ctx.track(() => { for (const p of panes.values()) { p.gone = true; if (p.C) p.C.dispose(); } panes.clear(); });
  function view() {
    const out = [];
    for (const id of want) {
      const p = panes.get(id);
      if (p) out.push({id, can: p.can !== false, stale: !!(p.data && (p.data.stale || p.err)), failed: !!(p.err && !p.data), why: p.ui && p.ui.msg ? p.ui.msg.textContent : ""});
    }
    return out;
  }
  return {
    /** the panes now wanted (at most two ids of PANES, in order) */
    set(ids) {
      want = ids.filter((x) => PANES[x]).slice(0, 2);
      for (const [id, p] of [...panes]) {
        if (want.includes(id)) continue;
        p.gone = true;
        if (p.C) p.C.dispose();
        if (p.el) p.el.remove();
        panes.delete(id);
      }
      for (const id of want) if (!panes.has(id)) build(id);
      sortHost();
    },
    onData(how) {
      if (how === "bar") {                       // the forming bar changes with every relay trade: the panes follow once a second
        if (!barTimer) barTimer = setTimeout(() => { barTimer = 0; for (const p of panes.values()) if (p.built) apply(p); }, 1000);
        return;
      }
      for (const p of panes.values()) {
        if (!p.built) continue;
        if (how === "set") {
          p.data = null; p.err = null;
          if (KIND_OF[p.id]) { apply(p); load(p, true); } else apply(p);
        } else apply(p);
      }
    },
    reload() { for (const p of panes.values()) if (KIND_OF[p.id] && p.built) load(p, true); },
    view,
  };
}

// #/replay?acct=<account id>&at=<entry_time ms> 거래 다시보기: ONE trade of one account, bar by bar. Copied and adapted from the rule bot's v4
// replay.js (nothing imported from it): the candles around the trade (the account's own timeframe, /api/klines), the entry and the exit as
// markers, the lines the record has (entry price, first stop, take-profit when there is one, the exit price), ▶ 재생 / ❚❚ / one bar ◀ ▶ /
// 1x 2x 4x, and a plain-Korean caption for the bar being shown ("진입: ...", "N봉 뒤 가장 유리했을 때 +x% (R)", "가장 불리했을 때 ...",
// "청산: ..."). The trade is found in /api/trades/<account> by its entry time (an open position by the snapshot's since).
// HONESTY: one trade's story, never a verdict (the page says so); a price the server hid reads 숨김 and is not drawn (never 0); the best /
// worst bars are looked up again in the bars (the record keeps only their prices) and are named only when a bar matches the price; the
// ladder's lock steps are NOT drawn (their prices and times are not in the trade record, the page says so). A failed load shows
// ui.errorBox with its retry. Read-only; every string reaches the page as a text node.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {loadLwc, color, tok} from "../chart.js";
import {TF_MS, tfKo, sideKo, reasonKo, coinOf, coinShort, ROLE_SHORT} from "../labels.js";
import {loadJudge} from "./pairs.js";
import {R_TITLE, rTxt, rMarks, whyIn, whyOut} from "../why.js";

export const css = ["scr/replay.css"];

const BEFORE = 20, AFTER = 8;               // bars shown before the entry bar and after the exit bar
const BASE_MS = 650, DWELL_MS = 1200;       // one bar at 1x; a bar with an event stays longer (time to read)
const SPEEDS = [{id: "1", label: "1x"}, {id: "2", label: "2x"}, {id: "4", label: "4x"}];
const MATCH = 0.002;                        // a bar's high / low is "the best / worst price" within 0.2%

const fin = (x) => x != null && x !== "" && typeof x !== "boolean" && Number.isFinite(Number(x));
const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };
const px = (p) => (fin(p) ? fmt.num(p, priceDec(p)) : "숨김");
const two = (n) => String(n).padStart(2, "0");
const kstD = (t) => new Date(t * 1000 + 9 * 3.6e6);

/** Index of the bar holding ``ms`` (the last bar opened at or before it), or -1 when ms is before the first bar. */
export function barAt(ts, ms) {
  let k = -1;
  for (let i = 0; i < ts.length && ts[i] <= ms; i++) k = i;
  return k;
}

/** The bars of the trade's best and worst moment, looked up in the bars between entry and exit: the bar whose high / low is the trade's
 *  mfe_price / mae_price (within 0.2%); null when the price is hidden or no bar matches (nothing is guessed). */
export function extremes(it, bars, ie, ix) {
  const d = it.side > 0 ? 1 : -1, out = {best: null, worst: null};
  // the bar holding the highest high (max) or the lowest low (not max) between entry and exit, the first one on a tie
  const scan = (max) => {
    let at = null;
    for (let k = Math.max(0, ie); k <= ix && k < bars.length; k++) {
      if (at == null || (max ? bars[k].h > bars[at].h : bars[k].l < bars[at].l)) at = k;
    }
    return at;
  };
  const match = (at, price, max) => (at != null && fin(price) && Math.abs((max ? bars[at].h : bars[at].l) - Number(price)) <= Math.abs(Number(price)) * MATCH ? at : null);
  out.best = match(scan(d > 0), it.mfe_price, d > 0);      // a long's best is its highest high, a short's its lowest low
  out.worst = match(scan(d < 0), it.mae_price, d < 0);
  return out;
}

/** The caption of bar ``k``: {kind: "before" | "entry" | "mid" | "exit" | "after", tone, lines: [string]}. S: {bars, ie, ix (null while open)}. */
export function moment(it, S, k) {
  const d = it.side > 0 ? 1 : -1;
  const e = fin(it.entry_price) ? Number(it.entry_price) : null;
  const r = e != null && fin(it.stop_initial) ? Math.abs(e - Number(it.stop_initial)) : 0;
  const how = (p) => {
    if (e == null || !fin(p)) return "가격 숨김";
    const m = d * (Number(p) / e - 1) * 100, x = r > 0 ? d * (Number(p) - e) / r : null;
    return `${fmt.pct(m, true, 2)}${x == null ? "" : ` (${rTxt(x)})`}`;
  };
  const after = (n) => (n > 0 ? `${fmt.int(n)}봉 뒤` : "진입한 봉 안에서");
  const coin = coinShort(coinOf(it.symbol));
  const exitLine = () => `청산: ${reasonKo(it.exit_reason)} · ${fin(it.exit_price) ? `${px(it.exit_price)} · ${how(it.exit_price)}` : "가격 숨김"}${fin(it.roe) ? ` · 증거금 대비 ${fmt.pct(it.roe * 100, true, 1)}` : ""}`;
  const lines = [];
  let kind = "mid", tone = "";
  if (k < S.ie) { kind = "before"; lines.push(`진입 ${fmt.int(S.ie - k)}봉 전: 아직 들어가지 않았습니다. 이 봉까지의 가격 흐름입니다.`); }
  else if (k === S.ie) {
    kind = "entry"; tone = "accent";
    lines.push(`진입: ${coin} ${sideKo(it.side)}${e == null ? " (가격 숨김)" : ` ${px(e)}`}${it.leverage ? ` · ${fmt.int(it.leverage)}배` : ""}`);
    if (fin(it.stop_initial)) lines.push(`${it.open ? "지금 손절" : "처음 손절"} ${px(it.stop_initial)}${r > 0 && e != null ? ` (가격 ${fmt.pct(r / e * 100, false, 2)} 거리 = 1R)` : ""}${fin(it.tp_price) ? ` · 익절 ${px(it.tp_price)}` : ""}`);
  } else if (S.ix != null && k > S.ix) { kind = "after"; lines.push(`청산 ${fmt.int(k - S.ix)}봉 뒤: 이 거래는 이미 끝났습니다. 그 뒤의 가격 흐름입니다.`); }
  else if (S.ix != null && k === S.ix) {
    kind = "exit"; tone = it.pnl != null ? (it.pnl > 0 ? "up" : "down") : (fin(it.roe) ? (it.roe > 0 ? "up" : "down") : "");
    lines.push(exitLine());
  } else {
    const b = S.bars[k];
    lines.push(`진입 ${fmt.int(k - S.ie)}봉 뒤 · 이 봉 마감 기준 ${how(b && b.c)}${it.open && S.ix == null && k === S.bars.length - 1 ? " · 아직 열려 있는 거래의 가장 최근 봉" : ""}`);
  }
  if (kind === "entry" && S.ix === k) lines.push(exitLine());           // entered and closed inside one bar
  if (k >= S.ie && (S.ix == null || k <= S.ix)) {
    if (S.best === k && k !== S.ie) lines.push(`${after(k - S.ie)} 가장 유리했을 때 ${how(it.mfe_price)}`);
    if (S.worst === k && k !== S.ie) lines.push(`${after(k - S.ie)} 가장 불리했을 때 ${how(it.mae_price)}`);
  }
  return {kind, tone, lines};
}

/** The lines the chart may draw for the trade: [{key, price, title, tok, style, from: "entry" | "exit"}]. No lock steps (not in the record). */
export function levels(it) {
  const out = [];
  const near = (p) => !it.open && fin(p) && fin(it.exit_price) && Math.abs(it.exit_price - p) <= Math.abs(it.exit_price) * 0.002;
  const atStop = near(it.stop_initial), atTp = !atStop && near(it.tp_price);
  if (fin(it.entry_price)) out.push({key: "entry", price: it.entry_price, title: "진입가", tok: "--ink-2", style: 2, from: "entry"});
  if (fin(it.stop_initial)) out.push({key: "stop", price: it.stop_initial, title: it.open ? "지금 손절" : atStop ? "처음 손절 = 청산" : "처음 손절", tok: "--down", style: 0, from: "entry"});
  if (fin(it.tp_price)) out.push({key: "tp", price: it.tp_price, title: atTp ? "익절 = 청산" : "익절", tok: "--up", style: 0, from: "entry"});
  if (!it.open && fin(it.exit_price) && !atStop && !atTp) {
    const win = it.pnl != null ? it.pnl > 0 : it.roe != null ? it.roe > 0 : null;
    out.push({key: "exit", price: it.exit_price, title: "청산가", tok: win === false ? "--down" : "--up", style: 1, from: "exit"});
  }
  return out;
}

export async function mount(el, ctx) {
  const q = ctx.params.query || {};
  const acctId = String(q.acct || ""), at = Number(q.at);
  const body = h("div", {class: "stack"});
  const head = h("div");
  el.classList.add("rp");
  el.append(head, body);
  let meta = null, judge = null, started = false, dispose = null;
  try { meta = await ctx.meta(); } catch (e) { /* codes */ }
  try { judge = await loadJudge(ctx); } catch (e) { /* the rule line is left out */ }
  if (!ctx.alive()) return null;

  put(head, ui.screenHead("거래 다시보기", "거래 한 건의 이야기 · 봉 하나씩 · 판정이 아닙니다"));
  if (!acctId || !fin(at) || !q.at) {
    put(body, ui.empty("어느 거래인지 알 수 없습니다 (계좌와 진입 시각이 필요합니다)"),
      h("p", null, h("a", {class: "btn-line", href: ctx.href("fills")}, "체결 기록에서 고르기")));
    return null;
  }
  const cleanup = () => { if (dispose) { try { dispose(); } catch (e) { /* gone */ } dispose = null; } };

  async function start(d) {
    const ix = LK.index(d), a = ix.byId[acctId];
    if (!a) { put(body, ui.empty("그런 계좌가 없습니다"), h("p", null, h("a", {class: "btn-line", href: ctx.href("rank")}, "순위표에서 고르기"))); return; }
    const c = LK.pickOf(a, ix) || a;
    const tf = a.tf || c.tf;
    put(head, ui.screenHead("거래 다시보기", `${LK.pickKo(c, meta)} · ${ROLE_SHORT[a.role] || a.role} 계좌 · 거래 한 건의 이야기 · 판정이 아닙니다`,
      [h("a", {class: "btn-line", href: ctx.href("account", a.id)}, "계좌"), h("a", {class: "btn-line", href: ctx.href("fills")}, "체결 기록")]));
    if (!TF_MS[tf]) { put(body, ui.errorBox(null, load)); return; }
    await load();

    async function load() {
      cleanup();
      put(body, ui.none("불러오는 중…"));
      let trades;
      try { trades = ((await ctx.api(`/api/trades/${encodeURIComponent(a.id)}`)) || {}).trades || []; } catch (e) {
        if (e && e.name === "AbortError") return;
        if (ctx.alive()) put(body, ui.errorBox(e, load));
        return;
      }
      const o = a.open && Number(a.open.since) === at ? a.open : null;
      const it = trades.find((x) => Number(x.entry_time) === at)
        || (o ? {open: true, symbol: o.symbol, side: o.side, entry_time: o.since, entry_price: o.entry, stop_initial: o.stop, tp_price: o.tp, leverage: o.lev} : null);
      if (!it) {
        put(body, ui.empty("이 거래를 기록에서 찾지 못했습니다 (계좌는 최근 200번까지만 기록에 남깁니다)"), h("p", null, h("a", {class: "btn-line", href: ctx.href("account", a.id)}, "계좌로")));
        return;
      }
      ctx.setTitle(`다시보기 · ${coinShort(coinOf(it.symbol))} ${sideKo(it.side)}`);
      const tfms = TF_MS[tf], endMs = it.open ? null : it.exit_time + AFTER * tfms;
      const span = Math.ceil(((it.open ? Date.now() : endMs) - it.entry_time) / tfms) + BEFORE;
      let kl;
      try { kl = await ctx.api(`/api/klines?coin=${coinOf(it.symbol)}&tf=${tf}&limit=${Math.max(120, Math.min(1000, span + 5))}${endMs ? `&end=${endMs}` : ""}`); } catch (e) {
        if (e && e.name === "AbortError") return;
        if (ctx.alive()) put(body, ui.errorBox(e, load));
        return;
      }
      if (!ctx.alive()) return;
      let L = null;
      try { L = await loadLwc(); } catch (e) { /* the story still reads without the chart */ }
      if (!ctx.alive()) return;
      render(a, c, tf, it, kl || {}, L);
    }
  }

  function render(a, c, tf, it, kl, L) {
    const tfms = TF_MS[tf], b = kl.bars;
    let all = [];
    if (b && b.t && b.t.length) all = b.t.map((t, k) => ({t, o: b.o[k], h: b.h[k], l: b.l[k], c: b.c[k]}));
    const e0 = barAt(all.map((x) => x.t), Math.floor(it.entry_time / tfms) * tfms);
    const x0 = it.open ? all.length - 1 : barAt(all.map((x) => x.t), it.exit_time - 1);
    const cut = all.length && e0 < 0;                     // the bars begin after the entry (a very long trade)
    const from = Math.max(0, (cut ? 0 : e0) - BEFORE), to = it.open ? all.length - 1 : Math.min(all.length - 1, x0 + AFTER);
    const bars = all.slice(from, to + 1);
    const n = bars.length;
    const ie = cut ? 0 : e0 - from, ix = it.open ? null : Math.max(ie, x0 - from);
    const S = {bars, ie, ix, ...(n ? extremes(it, bars, ie, ix == null ? n - 1 : ix) : {best: null, worst: null})};
    const last = ix == null ? n - 1 : ix;
    const lv = levels(it), rm = it.open ? null : rMarks(it);
    const noBars = n === 0 ? (kl.off ? "시세가 꺼져 있습니다 (CANDLEAGUE_DASH_LIVE=off)" : kl.unavailable ? "바이낸스 연결 안 됨 (잠시 뒤 다시)" : "이 거래 시간의 봉이 없습니다") : null;

    // ---- the caption and the controls
    const capStep = h("span", {class: "muted"});
    const capText = h("div", {class: "rp-cap-text", "aria-live": "polite"});
    const capWhy = h("div");
    const cap = h("div", {class: "rp-cap"}, h("div", {class: "rp-cap-top"}, h("span", {class: "rp-cap-plate"}, "지금 이 순간"), capStep), capText, capWhy);
    const btn = (label, aria, fn, cls = "") => h("button", {type: "button", class: ["btn-line", "rp-btn", cls], "aria-label": aria, onclick: fn}, label);
    const bPlay = btn("▶ 재생", "재생", () => (P.playing ? pause() : play()), "rp-play");
    const bFirst = btn("⏮ 진입", "진입한 봉으로", () => { pause(); goTo(ie); }, "rp-first");
    const bPrev = btn("◀", "한 봉 뒤로", () => { pause(); goTo(P.k - 1); }, "rp-prev");
    const bNext = btn("▶", "한 봉 앞으로", () => { pause(); goTo(P.k + 1); }, "rp-next");
    const bLast = btn(ix == null ? "⏭ 지금" : "⏭ 청산", ix == null ? "가장 최근 봉으로" : "청산한 봉으로", () => { pause(); goTo(last); }, "rp-last");
    const P = {k: ie, playing: false, speed: [1, 2, 4].includes(Number(local.get("replay-speed", "1"))) ? Number(local.get("replay-speed", "1")) : 1, t: null};
    const speed = ui.seg(SPEEDS, String(P.speed), (v) => { P.speed = Number(v) || 1; try { local.set("replay-speed", v); } catch (e) { /* kept for this page only */ } if (P.playing) schedule(); }, {label: "속도", cls: "rp-speed"});
    const ctl = h("div", {class: "rp-ctl", role: "group", "aria-label": "다시보기 조작"}, bFirst, bPrev, bPlay, bNext, bLast, speed);

    // ---- the chart (the library may be missing: the caption and the controls still work)
    const box = h("div", {class: "rp-chart", role: "img", "aria-label": `${coinShort(coinOf(it.symbol))} ${tfKo(tf)} 봉 차트, 이 거래의 진입과 청산`});
    const msg = h("p", {class: "note rp-msg"});
    let chart = null, candles = null, ro = null, lines = new Map();
    msg.hidden = true;
    if (noBars) { msg.hidden = false; msg.textContent = noBars; }
    else if (!L) { msg.hidden = false; msg.textContent = "차트 파일을 불러오지 못했습니다 · 아래 글과 조작 버튼으로 따라가 보세요"; }
    else if (cut) { msg.hidden = false; msg.textContent = "진입이 이 차트의 봉보다 앞입니다 (오래 보유한 거래): 보이는 첫 봉부터 보여 드립니다"; }
    function makeChart() {
      if (!L || chart || !n) return;
      try {
        chart = L.createChart(box, {width: box.clientWidth || 320, height: box.clientHeight || 260,
          layout: {background: {color: tok("--surface")}, textColor: tok("--ink-2"), fontSize: 11, fontFamily: tok("--f-body")},
          grid: {vertLines: {color: tok("--line")}, horzLines: {color: tok("--line")}},
          rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.12, bottom: 0.1}},
          timeScale: {borderColor: tok("--line-2"), timeVisible: true, secondsVisible: false, rightOffset: 2,
            tickMarkFormatter: (t, type) => { const dd = kstD(t); return type <= 2 ? `${dd.getUTCMonth() + 1}/${dd.getUTCDate()}` : `${two(dd.getUTCHours())}:${two(dd.getUTCMinutes())}`; }},
          crosshair: {mode: 0},
          localization: {locale: "ko-KR", timeFormatter: (t) => { const dd = kstD(t); return `${dd.getUTCMonth() + 1}/${dd.getUTCDate()} ${two(dd.getUTCHours())}:${two(dd.getUTCMinutes())} KST`; }},
          handleScroll: false, handleScale: false});
        const up = color("--up"), down = color("--down"), dec = priceDec(bars[n - 1].c);
        candles = chart.addCandlestickSeries({upColor: up, downColor: down, borderVisible: false, wickUpColor: up, wickDownColor: down,
          priceFormat: {type: "price", precision: dec, minMove: 10 ** -dec}, priceLineVisible: false, lastValueVisible: false});
        const keep = lv.map((x) => Number(x.price));
        if (keep.length) candles.applyOptions({autoscaleInfoProvider: (orig) => {
          const r = orig();
          if (!r || !r.priceRange) return r;
          return {...r, priceRange: {minValue: Math.min(r.priceRange.minValue, ...keep), maxValue: Math.max(r.priceRange.maxValue, ...keep)}};
        }});
        ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => { if (chart && box.clientWidth) chart.resize(box.clientWidth, box.clientHeight); }) : null;
        if (ro) ro.observe(box);
        chart.timeScale().fitContent();
      } catch (err) {
        chart = null; candles = null;
        msg.hidden = false; msg.textContent = "차트를 그리지 못했습니다 · 아래 글과 조작 버튼으로 따라가 보세요";
      }
    }
    /** The chart as of bar k: bars after k are drawn clear, the markers and lines the story has reached by k. */
    function paintChart(k) {
      if (!candles) return;
      const hide = "rgba(0,0,0,0)";
      candles.setData(bars.map((x, i) => (i <= k ? {time: x.t / 1000, open: x.o, high: x.h, low: x.l, close: x.c}
        : {time: x.t / 1000, open: x.o, high: x.h, low: x.l, close: x.c, color: hide, wickColor: hide, borderColor: hide})));
      const cIn = color("--accent"), cInS = color("--warn", "--down"), cWin = color("--up"), cLoss = color("--down");
      const ms = [];
      if (k >= ie) ms.push({time: bars[ie].t / 1000, position: it.side > 0 ? "belowBar" : "aboveBar", shape: it.side > 0 ? "arrowUp" : "arrowDown", color: it.side > 0 ? cIn : cInS, text: `진입 ${sideKo(it.side)}`});
      if (S.best != null && k >= S.best && S.best !== ie) ms.push({time: bars[S.best].t / 1000, position: it.side > 0 ? "aboveBar" : "belowBar", shape: "circle", color: cWin, text: "가장 유리"});
      if (S.worst != null && k >= S.worst && S.worst !== ie) ms.push({time: bars[S.worst].t / 1000, position: it.side > 0 ? "belowBar" : "aboveBar", shape: "circle", color: cLoss, text: "가장 불리"});
      if (ix != null && k >= ix) {
        const win = it.pnl != null ? it.pnl > 0 : it.roe != null ? it.roe > 0 : null;
        ms.push({time: bars[ix].t / 1000, position: it.side > 0 ? "aboveBar" : "belowBar", shape: "square", color: win === false ? cLoss : cWin,
          text: `청산 ${reasonKo(it.exit_reason)}`});
      }
      ms.sort((x, y) => x.time - y.time);
      candles.setMarkers(ms);
      for (const x of lv) {
        const want = x.from === "entry" ? k >= ie : ix != null && k >= ix;
        if (want && !lines.has(x.key)) lines.set(x.key, candles.createPriceLine({price: Number(x.price), color: color(x.tok), lineWidth: 1, lineStyle: x.style, axisLabelVisible: true, title: x.title}));
        else if (!want && lines.has(x.key)) { candles.removePriceLine(lines.get(x.key)); lines.delete(x.key); }
      }
    }
    function paintCaption(k) {
      const m = n ? moment(it, S, k) : {kind: "none", tone: "", lines: ["봉 자료가 없어 거래 기록의 숫자만 보여 드립니다. 아래 '거래 기록'을 보세요."]};
      put(capText, m.lines.map((x, i) => h("p", {class: i ? "rp-cap-sub" : "rp-cap-main"}, x)));
      cap.className = `rp-cap ${m.tone}`;
      const o = {c, acct: a, meta, judge};
      put(capWhy, m.kind === "entry" ? whyIn(it, o) : m.kind === "exit" ? whyOut(it, o) : null);
      const bar = bars[k];
      capStep.textContent = n ? `봉 ${fmt.int(k + 1)} / ${fmt.int(n)} · ${bar ? fmt.kst(bar.t) : ""} KST` : "";
    }
    function goTo(k) {
      if (!n) return;
      P.k = Math.max(0, Math.min(n - 1, k));
      paintCaption(P.k);
      paintChart(P.k);
      bFirst.disabled = P.k <= ie;
      bPrev.disabled = P.k <= 0;
      bNext.disabled = P.k >= n - 1;
      bLast.disabled = P.k >= last;
      bPlay.textContent = P.playing ? "❚❚ 멈춤" : P.k >= last ? "▶ 처음부터" : "▶ 재생";
    }
    function schedule() {
      clearTimeout(P.t);
      const m = moment(it, S, P.k);
      P.t = setTimeout(tick, (BASE_MS + (m.kind === "entry" || m.kind === "exit" || m.lines.length > 1 ? DWELL_MS : 0)) / P.speed);
    }
    function tick() {
      if (!P.playing) return;
      if (P.k >= last) { pause(); return; }
      goTo(P.k + 1);
      if (P.k >= last) pause(); else schedule();
    }
    function play() {
      if (!n) return;
      if (P.k >= last) goTo(ie);
      P.playing = true;
      bPlay.textContent = "❚❚ 멈춤";
      bPlay.setAttribute("aria-label", "멈춤");
      schedule();
    }
    function pause() {
      P.playing = false;
      clearTimeout(P.t);
      bPlay.textContent = P.k >= last ? "▶ 처음부터" : "▶ 재생";
      bPlay.setAttribute("aria-label", "재생");
    }
    const onVis = () => { if (document.hidden && P.playing) pause(); };
    document.addEventListener("visibilitychange", onVis);
    dispose = () => {
      clearTimeout(P.t); P.playing = false;
      document.removeEventListener("visibilitychange", onVis);
      if (ro) ro.disconnect();
      try { if (chart) chart.remove(); } catch (err) { /* gone */ }
      chart = null; candles = null; lines = new Map();
    };

    // ---- the trade record and the honesty lines
    const hold = (it.open ? Date.now() : it.exit_time) - it.entry_time;
    const hid = it.entry_price == null;
    const facts = ui.card({plate: "거래 기록", sub: "이 한 건의 기록 그대로", cls: "rp-facts"},
      ui.kv([["코인 · 방향", `${coinShort(coinOf(it.symbol))} ${sideKo(it.side)}${it.leverage ? ` · ${fmt.int(it.leverage)}배` : ""}`],
        ["진입", fmt.kst(it.entry_time)], ["청산", it.open ? "아직 열려 있음" : `${fmt.kst(it.exit_time)} · ${reasonKo(it.exit_reason)}`],
        ["보유", fmt.dur(hold / 1000)],
        ["진입가 → 청산가", hid ? "숨김" : `${px(it.entry_price)} → ${it.open ? "—" : px(it.exit_price)}`],
        [it.open ? "지금 손절" : "처음 손절", px(it.stop_initial)], ["익절", fin(it.tp_price) ? px(it.tp_price) : "없음 (계단 청산이면 익절 가격이 없습니다)"],
        ["증거금 대비", it.open ? "—" : fin(it.roe) ? fmt.pct(it.roe * 100, true, 1) : "숨김"], ["손익", it.open ? "—" : fin(it.pnl) ? fmt.money(it.pnl, true) : "숨김"],
        ["가장 유리 · 가장 불리", rm ? `${rTxt(rm.best)} · ${rTxt(-rm.worst)}` : "—"]]));
    const notes = h("ul", {class: "rp-notes"},
      h("li", null, "거래 한 건의 이야기입니다. 한 건으로 이 매매법이 좋다·나쁘다를 말할 수 없습니다 (판정은 판정 화면에서 정해진 날에 한 번)."),
      h("li", null, "그린 선은 진입가 · 처음 손절 · 익절 · 청산가뿐입니다. 계단 잠금선은 그리지 않습니다: 잠금 단계의 가격과 시각이 거래 기록에 남지 않기 때문입니다."),
      h("li", null, "'가장 유리·가장 불리' 봉은 봉 자료에서 그 가격을 다시 찾은 것입니다 (거래 기록에는 가격만 있음). 맞는 봉이 없으면 표시하지 않습니다."),
      h("li", null, R_TITLE));
    const chartCard = ui.card({plate: `${coinShort(coinOf(it.symbol))} · ${tfKo(tf)} 봉`, sub: "봉 하나씩 따라가기", cls: "rp-chartcard"},
      n ? box : null, msg, cap, n ? ctl : null);
    put(body, h("div", {class: "rp-grid"}, h("div", {class: "stack"}, chartCard), h("div", {class: "stack"}, facts, ui.card({plate: "읽을 때 주의"}, notes))));
    makeChart();
    if (n) goTo(ie); else paintCaption(0);
    pause();
  }

  ctx.onLeague((d) => { if (!started && d && d.accounts) { started = true; start(d); } });
  return cleanup;
}

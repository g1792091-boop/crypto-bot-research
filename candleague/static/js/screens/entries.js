// #/entries 진입 차트: one chart per pick, never several picks on one chart, grouped under each strategy with its entry
// rule. A chart shows the candles of the pick's own timeframe around ONE entry of the chosen account (후보 by default):
// the entry ▲▼, the exit ● with its reason, the entry and exit prices, and the stop / take-profit the trade was opened
// with (the live ones while it is open). Each strategy's section says how its 후보 trades end (손절 · 익절 · 계단 잠금,
// the median hold, in R the losers that first went +1R and the winners that first went −0.5R) and its pace toward 300.
// ◀ ▶ walks through that account's entries (the open position first, then the closed trades, newest first). A card
// loads its trades and candles only when it scrolls into view (38 charts never load at once). An open position shows
// its result now (가격 % and 증거금 대비 %, before fees like Binance's, from /api/live every 10 s) on a 지금 line and
// under the chart; its latest bars come in every minute while the card is on screen.
// Data: the shared snapshot (accounts, open positions), /api/trades/<account> per card, /api/klines?...&end= per entry,
// /api/live (the last price per coin).
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {loadLwc, color, tok} from "../chart.js";
import {ROLES, ROLE_KO, ROLE_SHORT, TFS, TF_MS, tfKo, sideKo, reasonKo, coinOf, coinShort, roleId} from "../labels.js";

const two = (n) => String(n).padStart(2, "0");
const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };
const px = (p) => (fmt.bad(p) ? "—" : fmt.num(p, priceDec(p)));
const BEFORE = 40, AFTER = 20;            // bars shown before the entry and after the exit
const LIVE_MS = 10_000, BARS_EVERY = 6;   // the price every 10 s; an open chart's latest bars every 6th time (1 min)
const OLD_MS = 30_000;                    // no fresh price for this long: shown as 지난 값, never as now
const R_TITLE = "R = 진입가와 처음 손절 사이 거리 (−1R = 처음 손절에 닿음 · 수수료 빼기 전 가격 기준)";
const REASON_ORDER = ["SL", "TP", "LOCK", "LIQ"];

/** A closed trade in R (|entry - first stop|): how far it went its way (best) and against it (worst) while open, and
 *  where it closed; null when a price is hidden or missing. summary.r_marks's rule. */
function rMarks(t) {
  const ks = ["entry_price", "stop_initial", "mfe_price", "mae_price", "exit_price"];
  if (ks.some((k) => t[k] == null || fmt.bad(t[k]))) return null;
  const e = Number(t.entry_price), r = Math.abs(e - Number(t.stop_initial)), d = t.side > 0 ? 1 : -1;
  if (!(r > 0)) return null;
  return {best: Math.max(0, d * (Number(t.mfe_price) - e) / r), worst: Math.max(0, d * (e - Number(t.mae_price)) / r),
    end: d * (Number(t.exit_price) - e) / r};
}
const rTxt = (x) => `${fmt.num(x, 1, true)}R`;
function reasonParts(rs) {
  const keys = [...REASON_ORDER.filter((k) => rs[k]), ...Object.keys(rs).filter((k) => !REASON_ORDER.includes(k))];
  return keys.map((k) => `${reasonKo(k)} ${fmt.int(rs[k])}`);
}

/** How a strategy's (or a pick's) closed trades went, in one wrapped line of small facts (summary.shape). */
function shapeLine(sh, who) {
  if (!sh || !sh.n) return h("div", {class: "cl-eshape"}, h("span", {class: "muted"}, `${who}: 아직 닫힌 거래가 없습니다`));
  const losers = sh.r_n - sh.r_wins;
  return h("div", {class: "cl-eshape"},
    h("span", null, h("b", null, who), ` 닫힌 ${fmt.int(sh.n)}번 · 이김 ${fmt.int(sh.wins)}`),
    h("span", null, reasonParts(sh.reasons || {}).join(" · ")),
    sh.hold_med_ms != null ? h("span", null, `보유 중앙 ${fmt.dur(sh.hold_med_ms / 1000)}`) : null,
    sh.r_n ? h("span", {title: `진 거래 중, 먼저 이득 쪽으로 1R 이상 갔던 거래 (벌었다가 놓침) · ${R_TITLE}`},
      `+1R 갔다가 진 거래 ${fmt.int(sh.gave_back)}/${fmt.int(losers)}`) : null,
    sh.r_n ? h("span", {title: `이긴 거래 중, 먼저 손해 쪽으로 0.5R 이상 갔던 거래 (버텨서 이김) · ${R_TITLE}`},
      `−0.5R 버티고 이긴 거래 ${fmt.int(sh.came_back)}/${fmt.int(sh.r_wins)}`) : null,
    sh.best_med != null ? h("span", {title: `거래 중 가장 유리했던 / 불리했던 지점의 중앙값 · ${R_TITLE}`},
      `가장 유리 중앙 ${rTxt(sh.best_med)} · 가장 불리 중앙 ${rTxt(-sh.worst_med)}`) : null);
}

export async function mount(el, ctx) {
  let meta = null;
  try { meta = await ctx.meta(); } catch (e) { /* names fall back to codes */ }
  const q = ctx.params.query || {};
  const st = {kind: ["core", "ds"].includes(q.kind) ? q.kind : "all", tf: TFS.includes(q.tf) ? q.tf : "all", strat: q.s || "all",
    role: ROLES.includes(q.role) ? q.role : "cand", only: q.only === "1"};
  const save = () => ctx.setQuery(Object.fromEntries(Object.entries({kind: st.kind, tf: st.tf, s: st.strat, role: st.role, only: st.only ? "1" : "all"})
    .filter(([k, v]) => v !== "all" && !(k === "role" && v === "cand"))));
  const L = await loadLwc().catch(() => null);
  if (!ctx.alive()) return null;

  const stratSel = h("div", {class: "cl-esel"});
  const info = h("p", {class: "note"});
  const list = h("div", {class: "stack"});
  el.append(
    ui.screenHead("진입 차트", "매매법마다 따로: 후보가 어디서 들어가고 어디서 나왔는지 · 차트 하나에 후보 하나"),
    h("div", {class: "dl-fields"},
      ui.field("종류", ui.seg([{id: "all", label: "전체"}, {id: "core", label: "기존 36"}, {id: "ds", label: "딥시크"}], st.kind, (v) => { st.kind = v; save(); paint(); }, {label: "종류"})),
      ui.field("봉", ui.seg([{id: "all", label: "전체"}, ...TFS.map((t) => ({id: t, label: tfKo(t)}))], st.tf, (v) => { st.tf = v; save(); paint(); }, {label: "봉"})),
      ui.field("매매법", stratSel),
      ui.field("계좌", ui.seg(ROLES.map((r) => ({id: r, label: ROLE_SHORT[r]})), st.role, (v) => { st.role = v; save(); paint(); }, {label: "계좌"})),
      ui.field("보기", ui.toggle("진입이 있는 것만", st.only, (v) => { st.only = v; save(); paint(); }, "아직 진입이 없는 후보는 숨기기"))),
    info, list);

  const cards = new Map();                 // account id -> card
  const io = typeof IntersectionObserver === "function"
    ? new IntersectionObserver((es) => { for (const e of es) if (e.isIntersecting) { io.unobserve(e.target); const c = byEl.get(e.target); if (c) c.show(); } }, {rootMargin: "400px 0px"})
    : null;
  const byEl = new WeakMap();
  // coin -> last price (/api/live), shared by every card; stale = the server could not refresh it (it keeps the last
  // good one), at = when this browser last got a fresh one, made = the server's time of the value
  const prices = {map: null, off: false, stale: false, fake: false, at: 0, made: null};
  const priceOld = () => prices.stale || !prices.at || Date.now() - prices.at > OLD_MS;
  const shapeBoxes = new Map();            // strategy name -> its section's shape + pace line (refreshed every snapshot)
  let sig = "";

  function paintSection(box, name, d) {
    const sw = ((d.watch || {}).strategies || {})[name];
    box.hidden = !sw;
    if (sw) put(box, shapeLine(sw.shape, "이 매매법 후보 전체"), LK.paceLine(d, sw.n, (d.watch || {}).min_trades || 300));
  }

  function picksNow(d) {
    const ix = LK.index(d);
    return ix.cands.filter((c) => (st.kind === "all" || c.kind === st.kind) && (st.tf === "all" || c.tf === st.tf)
      && (st.strat === "all" || c.name === st.strat))
      .map((c) => ({c, a: ix.byId[roleId(c, st.role)] || null}))
      .filter((x) => x.a && (!st.only || x.a.trades || x.a.open));
  }
  function paint() {
    const d = LK.league();
    if (!d || !d.accounts) { put(list, ui.none("준비 중")); return; }
    const ix = LK.index(d);
    const names = [...new Set(ix.cands.map((c) => c.name))].sort((x, y) => LK.stratKo(x, meta).localeCompare(LK.stratKo(y, meta), "ko"));
    put(stratSel, ui.select([{id: "all", label: `전체 (${names.length}개)`}, ...names.map((n) => ({id: n, label: `${LK.stratKo(n, meta)} (${n})`}))],
      st.strat, (v) => { st.strat = v; save(); paint(); }, "매매법"));
    const rows = picksNow(d);
    const s2 = rows.map((x) => x.a.id).join();
    if (s2 === sig) {
      for (const x of rows) { const c = cards.get(x.a.id); if (c) c.update(x.a); }
      for (const [name, box] of shapeBoxes) paintSection(box, name, d);
      return;
    }
    sig = s2;
    shapeBoxes.clear();
    for (const c of cards.values()) c.destroy();
    cards.clear();
    if (io) io.disconnect();
    if (!rows.length) { put(list, ui.empty("조건에 맞는 후보가 없습니다")); info.textContent = ""; return; }
    const groups = new Map();
    for (const x of rows) { if (!groups.has(x.c.name)) groups.set(x.c.name, []); groups.get(x.c.name).push(x); }
    const order = [...groups.keys()].sort((x, y) => (groups.get(x)[0].c.kind === groups.get(y)[0].c.kind ? 0 : groups.get(x)[0].c.kind === "core" ? -1 : 1)
      || LK.stratKo(x, meta).localeCompare(LK.stratKo(y, meta), "ko"));
    put(list, order.map((name) => {
      const xs = groups.get(name).sort((a, b) => TFS.indexOf(a.c.tf) - TFS.indexOf(b.c.tf));
      const sm = LK.stratMeta(name, meta) || {};
      const sbox = h("div", {class: "cl-eshapes"});
      shapeBoxes.set(name, sbox);
      paintSection(sbox, name, d);
      return ui.card({plate: LK.stratKo(name, meta), sub: `${name}${sm.family ? ` · ${sm.family}` : ""}`, cls: "cl-esec",
        acts: h("span", {class: "row wrap"}, LK.kindChip(xs[0].c.kind), h("a", {class: "btn-line", href: `#/strategies?s=${encodeURIComponent(name)}`}, "매매법 설명"))},
      sm.long || sm.short ? h("dl", {class: "cl-erule"},
        sm.long ? h("div", null, h("dt", null, h("span", {class: "side long"}, "롱")), h("dd", null, sm.long)) : null,
        sm.short ? h("div", null, h("dt", null, h("span", {class: "side short"}, "숏")), h("dd", null, sm.short)) : null) : null,
      sbox,
      h("div", {class: "cl-egrid"}, xs.map((x) => {
        const card = makeCard(x.c, x.a);
        cards.set(x.a.id, card);
        byEl.set(card.el, card);
        if (io) io.observe(card.el); else card.show();
        return card.el;
      })));
    }));
    const withEntry = rows.filter((x) => x.a.trades || x.a.open).length;
    info.textContent = `후보 ${rows.length}개 중 진입이 있는 것 ${withEntry}개 · ${ROLE_KO[st.role]} 계좌의 진입 · ` +
      "차트마다 그 후보의 봉(15분 · 30분 · 1시간 · 4시간) · ◀ ▶로 다른 진입 · 한국 시각 · " +
      "선: 진입가(점선) · 처음 손절(빨강) · 익절(초록, 계단 청산이면 없음) · 청산가 · 열린 포지션은 '지금' 선과 +% −% (10초마다) · " + R_TITLE;
  }

  // ------------------------------------------------------------ one pick's card
  function makeCard(c, a) {
    let acct = a, items = [], i = 0, loaded = false, failed = false, count = -1, chart = null, candles = null, plines = [], ro = null, seq = 0;
    let nowLine = null, liveRow = null, lastBar = 0, ticks = 0, barsBusy = false;
    let drawnItem = null;                  // the item whose candles the chart holds (null while a draw is pending or failed)
    const box = h("div", {class: "cl-ebox"});
    const msgEl = h("div", {class: "cl-emsg"});
    const cap = h("div", {class: "cl-ecap"});
    const pos = h("span", {class: "num muted"});
    const prev = h("button", {type: "button", class: "btn-line sm", "aria-label": "더 최근 진입", onclick: () => step(-1)}, "◀");
    const next = h("button", {type: "button", class: "btn-line sm", "aria-label": "이전 진입", onclick: () => step(1)}, "▶");
    const link = h("a", {class: "btn-line sm"}, "터미널");
    const shapeEl = h("div", {class: "cl-epick"});
    const wrap = h("div", {class: "cl-ewrap"}, box, msgEl);
    const nav = h("div", {class: "cl-enav"}, prev, pos, next, h("span", {class: "grow"}), link);
    const el = h("article", {class: "cl-ecard"},
      h("div", {class: "cl-ehead"}, h("span", {class: "an-tf"}, tfKo(c.tf)), h("b", null, LK.stratKo(c.name, meta)), LK.roleChip(acct.role, ROLE_SHORT[acct.role]),
        h("span", {class: "grow"}), h("a", {class: "cl-elink", href: `#/account/${encodeURIComponent(acct.id)}`}, "계좌")),
      shapeEl, nav,
      wrap, cap);
    paintShape();
    paintNav();

    function paintShape() {
      const w = (LK.league() || {}).watch || {};
      const sh = acct.role === "cand" ? ((w.picks || {})[c.id] || {}).shape : null;
      shapeEl.hidden = !(sh && sh.n);
      if (sh && sh.n) put(shapeEl, `닫힌 ${fmt.int(sh.n)}번 · ${reasonParts(sh.reasons || {}).join(" · ")}`);
    }

    function entries() {
      const out = [];
      if (acct.open) out.push({open: true, symbol: acct.open.symbol, side: acct.open.side, entry_time: acct.open.since, entry_price: acct.open.entry,
        stop: acct.open.stop, tp: acct.open.tp, lev: acct.open.lev});
      return out;
    }
    async function load() {
      const n = acct.trades;
      let trades = [];
      failed = false;
      if (n) {
        try { trades = ((await ctx.api(`/api/trades/${encodeURIComponent(acct.id)}`)) || {}).trades || []; } catch (e) {
          if (e && e.name === "AbortError") return false;
          failed = true;                         // shown as such, never as "no entry yet"; the next snapshot tries again
          count = -1;
        }
      }
      items = [...entries(), ...trades];
      if (!failed) count = n;
      if (i >= items.length) i = 0;
      return true;
    }
    async function show() {
      if (loaded) return;
      loaded = true;
      if (!(await load()) || !ctx.alive()) return;
      paintNav();
      draw();
    }
    async function update(a2) {
      const opened = JSON.stringify(a2.open || null) !== JSON.stringify(acct.open || null);
      acct = a2;
      paintShape();
      if (!loaded || (a2.trades === count && !opened)) return;
      const wasFirst = i === 0;
      if (!(await load()) || !ctx.alive()) return;
      if (wasFirst) i = 0;
      paintNav();
      draw();
    }
    function step(d) {
      if (!items.length) return;
      i = Math.max(0, Math.min(items.length - 1, i + d));
      paintNav();
      draw();
    }
    function paintNav() {
      const n = loaded ? items.length : (acct.trades || 0) + (acct.open ? 1 : 0);
      wrap.hidden = nav.hidden = !n;          // no entry yet: a short line instead of an empty chart
      if (!n) put(cap, h("span", {class: "muted"}, failed ? "거래 기록을 불러오지 못했습니다 (잠시 뒤 다시)" : "아직 진입이 없습니다 · 들어가면 여기에 차트가 나옵니다"));
      pos.textContent = n ? `${i + 1} / ${n}` : "진입 없음";
      prev.disabled = i <= 0;
      next.disabled = i >= n - 1;
      const it = items[i];
      link.href = it ? `#/terminal?acct=${encodeURIComponent(acct.id)}&coin=${coinOf(it.symbol)}&at=${it.entry_time}` : `#/terminal?acct=${encodeURIComponent(acct.id)}`;
    }
    function msg(text) { msgEl.hidden = !text; msgEl.textContent = text || ""; }
    function makeChart() {
      if (chart || !L) return;
      chart = L.createChart(box, {width: box.clientWidth || 320, height: box.clientHeight || 220,
        layout: {background: {color: tok("--surface")}, textColor: tok("--ink-2"), fontSize: 11, fontFamily: tok("--f-body")},
        grid: {vertLines: {color: tok("--line")}, horzLines: {color: tok("--line")}},
        rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.12, bottom: 0.1}},
        timeScale: {borderColor: tok("--line-2"), timeVisible: true, secondsVisible: false, rightOffset: 3,
          tickMarkFormatter: (t, type) => { const d = new Date(t * 1000 + 9 * 3.6e6); return type <= 2 ? `${d.getUTCMonth() + 1}/${d.getUTCDate()}` : `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`; }},
        crosshair: {mode: 0},
        localization: {locale: "ko-KR", timeFormatter: (t) => { const d = new Date(t * 1000 + 9 * 3.6e6); return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${two(d.getUTCHours())}:${two(d.getUTCMinutes())} KST`; }},
        handleScroll: {mouseWheel: false, pressedMouseMove: true, horzTouchDrag: false, vertTouchDrag: false},
        handleScale: {mouseWheel: false, pinch: false, axisPressedMouseMove: false, axisDoubleClickReset: true}});
      const up = color("--up"), down = color("--down");
      candles = chart.addCandlestickSeries({upColor: up, downColor: down, borderVisible: false, wickUpColor: up, wickDownColor: down});
      ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => { if (chart && box.clientWidth) chart.resize(box.clientWidth, box.clientHeight); }) : null;
      if (ro) ro.observe(box);
    }
    async function draw() {
      const it = items[i];
      if (!it) { if (acct.trades || acct.open) msg("불러오지 못했습니다"); return; }
      if (!L) { msg("차트 파일을 불러오지 못했습니다"); caption(it); return; }
      const my = ++seq;
      drawnItem = null;                      // the chart still holds the previous item's candles until setData
      const coin = coinOf(it.symbol), tfms = TF_MS[c.tf];
      const endMs = it.open ? null : it.exit_time + AFTER * tfms;
      const span = Math.ceil(((it.open ? Date.now() : endMs) - it.entry_time) / tfms) + BEFORE;
      const limit = Math.max(120, Math.min(1000, span + 5));
      msg("불러오는 중…");
      let d;
      try { d = await ctx.api(`/api/klines?coin=${coin}&tf=${c.tf}&limit=${limit}${endMs ? `&end=${endMs}` : ""}`); } catch (e) {
        if (!(e && e.name === "AbortError") && my === seq) msg("차트 자료를 불러오지 못했습니다 (잠시 뒤 다시)");
        return;
      }
      if (my !== seq || !ctx.alive()) return;
      if (d.off) { msg("시세가 꺼져 있습니다 (CANDLEAGUE_DASH_LIVE=off)"); caption(it); return; }
      const b = d.bars;
      if (!b || !b.t || !b.t.length) { msg(d.unavailable ? "바이낸스 연결 안 됨 (잠시 뒤 다시)" : "봉이 없습니다"); caption(it); return; }
      makeChart();
      msg("");
      const n = b.t.length, dec = priceDec(b.c[n - 1]);
      lastBar = b.t[n - 1];
      // the latest price line only while the position is open (a past trade's chart ends after its exit)
      candles.applyOptions({priceFormat: {type: "price", precision: dec, minMove: 10 ** -dec}, priceLineVisible: !!it.open, lastValueVisible: !!it.open});
      candles.setData(b.t.map((t, k) => ({time: t / 1000, open: b.o[k], high: b.h[k], low: b.l[k], close: b.c[k]})));
      drawnItem = it;
      const barT = (ms) => (Math.floor(ms / tfms) * tfms) / 1000;
      const first = b.t[0];
      const cIn = color("--accent"), cInS = color("--warn", "--down"), cWin = color("--up"), cLoss = color("--down");
      const ms = [];
      if (it.entry_time >= first) ms.push({time: barT(it.entry_time), position: it.side > 0 ? "belowBar" : "aboveBar", shape: it.side > 0 ? "arrowUp" : "arrowDown",
        color: it.side > 0 ? cIn : cInS, text: `진입 ${sideKo(it.side)}`});
      if (!it.open && it.exit_time >= first) {
        const win = it.pnl != null ? it.pnl > 0 : it.roe != null ? it.roe > 0 : it.win != null ? !!it.win : null;
        ms.push({time: barT(it.exit_time - 1), position: it.side > 0 ? "aboveBar" : "belowBar", shape: "circle", color: win === false ? cLoss : cWin,
          text: `${reasonKo(it.exit_reason)}${it.roe == null ? "" : ` ${fmt.pct(it.roe * 100, true, 0)}`}`});
      }
      ms.sort((x, y) => x.time - y.time);
      candles.setMarkers(ms);
      for (const p of plines) candles.removePriceLine(p);
      plines = [];
      nowLine = null;
      const line = (p, col, title, style) => { if (p != null && !fmt.bad(p)) plines.push(candles.createPriceLine({price: p, color: col, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title})); };
      line(it.entry_price, color("--ink-2"), "진입가", 2);
      // the plan the trade was opened with (the live stop / take-profit while open), kept in view by the price scale
      const plan = it.open ? [it.stop, it.tp] : [it.stop_initial, it.tp_price];
      // an exit at (about) a planned level shares that line instead of a second label on top of it
      const near = (p) => !it.open && p != null && !fmt.bad(p) && it.exit_price != null && Math.abs(it.exit_price - p) <= Math.abs(it.exit_price) * 0.002;
      const atStop = near(plan[0]), atTp = !atStop && near(plan[1]);
      line(plan[0], color("--down"), it.open ? "손절" : atStop ? "처음 손절 = 청산" : "처음 손절", 0);
      line(plan[1], color("--up"), atTp ? "익절 = 청산" : "익절", 0);
      if (!it.open && !atStop && !atTp) line(it.exit_price, win(it) === false ? color("--down") : color("--up"), "청산가", 1);
      const lv = plan.filter((p) => p != null && !fmt.bad(p)).map(Number);
      candles.applyOptions({autoscaleInfoProvider: (orig) => {
        const r = orig();
        if (!r || !r.priceRange || !lv.length) return r;
        return {...r, priceRange: {minValue: Math.min(r.priceRange.minValue, ...lv), maxValue: Math.max(r.priceRange.maxValue, ...lv)}};
      }});
      const from = Math.max(first / 1000, barT(it.entry_time) - BEFORE * tfms / 1000);
      const to = it.open ? b.t[n - 1] / 1000 + 2 * tfms / 1000 : barT(it.exit_time) + Math.min(AFTER, 12) * tfms / 1000;
      try { chart.timeScale().setVisibleRange({from, to}); } catch (e) { chart.timeScale().fitContent(); }
      if (it.entry_time < first) msg("진입이 이 차트보다 앞입니다 (터미널에서 보기)");
      caption(it);
      paintLive();
    }

    // ---------------------------------------------------------- an open position now (every LIVE_MS)
    /** {price, move: 가격 % (side-signed), roe: 증거금 대비 % (move × leverage, before fees; never below −100%, an
     *  isolated position's most), past: "stop" | "tp" when the price is beyond the stop / take-profit the engine has not
     *  booked yet (it works every 5 minutes), old: the price is not fresh} of the open item, or null. */
    function liveNow(it) {
      const r = it && it.open && prices.map ? prices.map[coinOf(it.symbol)] : null;
      if (!r || r.price == null || fmt.bad(r.price) || it.entry_price == null || fmt.bad(it.entry_price)) return null;
      const move = it.side * (r.price / it.entry_price - 1) * 100;
      const beyond = (lvl, worse) => lvl != null && !fmt.bad(lvl) && (worse ? it.side * (r.price - lvl) <= 0 : it.side * (r.price - lvl) >= 0);
      return {price: r.price, move, roe: it.lev ? Math.max(-100, move * it.lev) : null,
        past: beyond(it.stop, true) ? "stop" : beyond(it.tp, false) ? "tp" : null, old: priceOld()};
    }
    function paintLive() {
      const it = items[i];
      const m = liveNow(it);
      if (liveRow) {
        const tone = (x) => (m.old ? "muted" : fmt.tone(x));
        put(liveRow, m ? [h("span", {class: "muted"}, m.old ? "지난 값" : "지금"), h("span", {class: "num"}, px(m.price)),
          h("span", {class: ["num", "cl-elive-pct", tone(m.move)]}, `가격 ${fmt.pct(m.move, true, 2)}`),
          m.roe != null ? h("span", {class: ["num", "cl-elive-pct", tone(m.roe)]}, `증거금 대비 ${fmt.pct(m.roe, true, 1)}`) : null,
          m.past ? ui.pill(m.past === "stop" ? "손절선 지남 · 다음 계산(5분마다)에 청산" : "익절선 지남 · 다음 계산(5분마다)에 청산", "warn") : null,
          h("span", {class: "muted"}, `${it.lev ? `${fmt.int(it.lev)}배 · ` : ""}수수료 전 · ` + (m.old
            ? `시세 연결 확인 중${prices.made ? ` (${fmt.hms(prices.made)} 값)` : ""}` : prices.fake ? "연습용 가짜 시세" : "10초마다"))]
          : h("span", {class: "muted"}, !it || it.entry_price == null || prices.off ? "" : "지금 가격을 기다리는 중…"));
      }
      if (!candles || drawnItem !== it) return;  // the chart holds another item's candles (a draw is pending or failed)
      if (!m) {
        if (nowLine) { candles.removePriceLine(nowLine); plines = plines.filter((p) => p !== nowLine); nowLine = null; }
        if (it && it.open) candles.applyOptions({priceLineVisible: true, lastValueVisible: true});
        return;
      }
      const opt = {price: m.price, color: m.old ? color("--muted") : m.move > 0 ? color("--up") : m.move < 0 ? color("--down") : color("--ink-2"),
        lineWidth: 1, lineStyle: 3, axisLabelVisible: true, title: `${m.old ? "지난 값" : "지금"} ${fmt.pct(m.roe != null ? m.roe : m.move, true, 1)}`};
      if (nowLine) nowLine.applyOptions(opt); else { nowLine = candles.createPriceLine(opt); plines.push(nowLine); }
      candles.applyOptions({priceLineVisible: false, lastValueVisible: false});   // the 지금 line carries the price
    }
    function onScreen() {
      const r = el.getBoundingClientRect();
      return r.bottom > 0 && r.top < (window.innerHeight || 800);
    }
    /** The latest bars of an open position's chart (the newest bar grows, a new one appears) without moving the view. */
    async function moreBars() {
      const it = items[i];
      if (!it || !it.open || !candles || drawnItem !== it || barsBusy) return;
      barsBusy = true;
      const my = seq;
      try {
        const d = await ctx.api(`/api/klines?coin=${coinOf(it.symbol)}&tf=${c.tf}&limit=50`);
        const b = d && d.bars;
        if (my !== seq || !candles || drawnItem !== it || !b || !b.t || !b.t.length) return;
        if (b.t[0] > lastBar + TF_MS[c.tf]) { draw(); return; }        // away longer than these bars cover: draw again
        for (let k = 0; k < b.t.length; k++) {
          if (b.t[k] < lastBar) continue;
          candles.update({time: b.t[k] / 1000, open: b.o[k], high: b.h[k], low: b.l[k], close: b.c[k]});
          lastBar = b.t[k];
        }
      } catch (e) { /* the next minute tries again */ } finally { barsBusy = false; }
    }
    function tick() {
      const it = items[i];
      if (!loaded || !it || !it.open) return;
      paintLive();
      if (++ticks % BARS_EVERY === 0 && onScreen()) moreBars();
    }
    const win = (t) => (t.pnl != null ? t.pnl > 0 : t.roe != null ? t.roe > 0 : t.win != null ? !!t.win : null);
    function caption(it) {
      liveRow = null;
      const hold = (it.open ? Date.now() : it.exit_time) - it.entry_time;
      put(cap,
        h("div", {class: "cl-ecl"}, h("b", null, coinShort(coinOf(it.symbol))), h("span", {class: ["side", it.side > 0 ? "long" : "short"]}, sideKo(it.side)),
          h("span", {class: "muted"}, `진입 ${fmt.kst(it.entry_time)}`), it.entry_price == null ? h("span", {class: "muted"}, "가격 숨김") : h("span", {class: "num"}, px(it.entry_price))),
        it.open
          ? [h("div", {class: "cl-ecl"}, ui.pill("지금 열림", "accent"), h("span", {class: "muted"}, `${fmt.dur(hold / 1000)}째`),
            it.stop != null ? h("span", {class: "muted"}, `손절 ${px(it.stop)}`) : null, it.tp != null ? h("span", {class: "muted"}, `익절 ${px(it.tp)}`) : null),
            (liveRow = h("div", {class: "cl-ecl cl-elive", "aria-live": "off"}))]
          : h("div", {class: "cl-ecl"}, h("span", {class: "muted"}, `청산 ${fmt.kst(it.exit_time)}`), h("b", null, reasonKo(it.exit_reason)),
            it.leverage ? h("span", {class: "muted"}, `${fmt.int(it.leverage)}배`) : null,
            it.roe == null ? h("span", {class: "muted"}, win(it) == null ? "" : win(it) ? "이김" : "짐")
              : h("span", {class: ["num", fmt.tone(it.roe)]}, `증거금 대비 ${fmt.pct(it.roe * 100, true, 1)}`),
            ((mv) => (mv == null ? null : h("span", {class: ["num", fmt.tone(mv)], title: "진입가에서 청산가까지 (방향 반영, 레버리지 전)"}, `가격 ${fmt.pct(mv, true, 2)}`)))(
              it.entry_price != null && it.exit_price != null && !fmt.bad(it.entry_price) && !fmt.bad(it.exit_price)
                ? it.side * (it.exit_price / it.entry_price - 1) * 100 : null),
            h("span", {class: "muted"}, `보유 ${fmt.dur(hold / 1000)}`)),
        it.open ? null : ((m) => (m ? h("div", {class: "cl-ecl", title: R_TITLE},
          h("span", {class: "muted"}, "가장 유리"), h("span", {class: "num"}, rTxt(m.best)),
          h("span", {class: "muted"}, "가장 불리"), h("span", {class: "num"}, rTxt(-m.worst)),
          h("span", {class: "muted"}, "청산"), h("span", {class: ["num", fmt.tone(m.end)]}, rTxt(m.end)),
          !win(it) && m.best >= 1 ? ui.pill("벌었다가 놓침", "warn") : null) : null))(rMarks(it)));
    }
    function destroy() {
      seq++;
      if (ro) ro.disconnect();
      try { if (chart) chart.remove(); } catch (e) { /* gone */ }
      chart = null; candles = null; nowLine = null; drawnItem = null;
    }
    return {el, show, update, destroy, tick};
  }

  async function pollLive() {
    let d = null;
    try { d = await ctx.api("/api/live"); } catch (e) { if (e && e.name === "AbortError") return; }
    if (d) {                                 // a failed request keeps the last prices, which then age into 지난 값
      const map = {};
      for (const r of d.coins || []) if (r && r.coin && r.price != null) map[r.coin] = r;
      prices.off = !!d.off;
      prices.stale = !!(d.stale || d.unavailable);
      prices.fake = d.source === "fake";
      if (prices.off) prices.map = null;
      else if (Object.keys(map).length) { prices.map = map; prices.made = d.generated_ms || null; if (!prices.stale) prices.at = Date.now(); }
    }
    for (const c of cards.values()) c.tick();
  }
  ctx.onLeague(paint);
  pollLive();
  ctx.every(LIVE_MS, pollLive);
  return () => { if (io) io.disconnect(); for (const c of cards.values()) c.destroy(); };
}

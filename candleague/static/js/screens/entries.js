// #/entries 진입 차트: one chart per pick, never several picks on one chart, grouped under each strategy with its entry
// rule. A chart shows the candles of the pick's own timeframe around ONE entry of the chosen account (후보 by default):
// the entry ▲▼, the exit ● with its reason, the entry price, and the stop / take-profit while the position is open.
// ◀ ▶ walks through that account's entries (the open position first, then the closed trades, newest first). A card
// loads its trades and candles only when it scrolls into view (38 charts never load at once).
// Data: the shared snapshot (accounts, open positions), /api/trades/<account> per card, /api/klines?...&end= per entry.
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
  let sig = "";

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
    if (s2 === sig) { for (const x of rows) { const c = cards.get(x.a.id); if (c) c.update(x.a); } return; }
    sig = s2;
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
      return ui.card({plate: LK.stratKo(name, meta), sub: `${name}${sm.family ? ` · ${sm.family}` : ""}`, cls: "cl-esec",
        acts: h("span", {class: "row wrap"}, LK.kindChip(xs[0].c.kind), h("a", {class: "btn-line", href: `#/strategies?s=${encodeURIComponent(name)}`}, "매매법 설명"))},
      sm.long || sm.short ? h("dl", {class: "cl-erule"},
        sm.long ? h("div", null, h("dt", null, h("span", {class: "side long"}, "롱")), h("dd", null, sm.long)) : null,
        sm.short ? h("div", null, h("dt", null, h("span", {class: "side short"}, "숏")), h("dd", null, sm.short)) : null) : null,
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
      "차트마다 그 후보의 봉(15분 · 30분 · 1시간 · 4시간) · ◀ ▶로 다른 진입 · 한국 시각";
  }

  // ------------------------------------------------------------ one pick's card
  function makeCard(c, a) {
    let acct = a, items = [], i = 0, loaded = false, failed = false, count = -1, chart = null, candles = null, plines = [], ro = null, seq = 0;
    const box = h("div", {class: "cl-ebox"});
    const msgEl = h("div", {class: "cl-emsg"});
    const cap = h("div", {class: "cl-ecap"});
    const pos = h("span", {class: "num muted"});
    const prev = h("button", {type: "button", class: "btn-line sm", "aria-label": "더 최근 진입", onclick: () => step(-1)}, "◀");
    const next = h("button", {type: "button", class: "btn-line sm", "aria-label": "이전 진입", onclick: () => step(1)}, "▶");
    const link = h("a", {class: "btn-line sm"}, "터미널");
    const wrap = h("div", {class: "cl-ewrap"}, box, msgEl);
    const nav = h("div", {class: "cl-enav"}, prev, pos, next, h("span", {class: "grow"}), link);
    const el = h("article", {class: "cl-ecard"},
      h("div", {class: "cl-ehead"}, h("span", {class: "an-tf"}, tfKo(c.tf)), h("b", null, LK.stratKo(c.name, meta)), LK.roleChip(acct.role, ROLE_SHORT[acct.role]),
        h("span", {class: "grow"}), h("a", {class: "cl-elink", href: `#/account/${encodeURIComponent(acct.id)}`}, "계좌")),
      nav,
      wrap, cap);
    paintNav();

    function entries() {
      const out = [];
      if (acct.open) out.push({open: true, symbol: acct.open.symbol, side: acct.open.side, entry_time: acct.open.since, entry_price: acct.open.entry,
        stop: acct.open.stop, tp: acct.open.tp});
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
      candles.applyOptions({priceFormat: {type: "price", precision: dec, minMove: 10 ** -dec}});
      candles.setData(b.t.map((t, k) => ({time: t / 1000, open: b.o[k], high: b.h[k], low: b.l[k], close: b.c[k]})));
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
      const line = (p, col, title, style) => { if (p != null && !fmt.bad(p)) plines.push(candles.createPriceLine({price: p, color: col, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title})); };
      line(it.entry_price, color("--ink-2"), "진입가", 2);
      if (it.open) { line(it.stop, color("--down"), "손절", 0); line(it.tp, color("--up"), "익절", 0); }
      else line(it.exit_price, win(it) === false ? color("--down") : color("--up"), "청산가", 1);
      const from = Math.max(first / 1000, barT(it.entry_time) - BEFORE * tfms / 1000);
      const to = it.open ? b.t[n - 1] / 1000 + 2 * tfms / 1000 : barT(it.exit_time) + Math.min(AFTER, 12) * tfms / 1000;
      try { chart.timeScale().setVisibleRange({from, to}); } catch (e) { chart.timeScale().fitContent(); }
      if (it.entry_time < first) msg("진입이 이 차트보다 앞입니다 (터미널에서 보기)");
      caption(it);
    }
    const win = (t) => (t.pnl != null ? t.pnl > 0 : t.roe != null ? t.roe > 0 : t.win != null ? !!t.win : null);
    function caption(it) {
      const hold = (it.open ? Date.now() : it.exit_time) - it.entry_time;
      put(cap,
        h("div", {class: "cl-ecl"}, h("b", null, coinShort(coinOf(it.symbol))), h("span", {class: ["side", it.side > 0 ? "long" : "short"]}, sideKo(it.side)),
          h("span", {class: "muted"}, `진입 ${fmt.kst(it.entry_time)}`), it.entry_price == null ? h("span", {class: "muted"}, "가격 숨김") : h("span", {class: "num"}, px(it.entry_price))),
        it.open
          ? h("div", {class: "cl-ecl"}, ui.pill("지금 열림", "accent"), h("span", {class: "muted"}, `${fmt.dur(hold / 1000)}째`),
            it.stop != null ? h("span", {class: "muted"}, `손절 ${px(it.stop)}`) : null, it.tp != null ? h("span", {class: "muted"}, `익절 ${px(it.tp)}`) : null)
          : h("div", {class: "cl-ecl"}, h("span", {class: "muted"}, `청산 ${fmt.kst(it.exit_time)}`), h("b", null, reasonKo(it.exit_reason)),
            it.leverage ? h("span", {class: "muted"}, `${fmt.int(it.leverage)}배`) : null,
            it.roe == null ? h("span", {class: "muted"}, win(it) == null ? "" : win(it) ? "이김" : "짐")
              : h("span", {class: ["num", fmt.tone(it.roe)]}, `증거금 대비 ${fmt.pct(it.roe * 100, true, 1)}`),
            h("span", {class: "muted"}, `보유 ${fmt.dur(hold / 1000)}`)));
    }
    function destroy() {
      seq++;
      if (ro) ro.disconnect();
      try { if (chart) chart.remove(); } catch (e) { /* gone */ }
      chart = null; candles = null;
    }
    return {el, show, update, destroy};
  }

  ctx.onLeague(paint);
  return () => { if (io) io.disconnect(); for (const c of cards.values()) c.destroy(); };
}

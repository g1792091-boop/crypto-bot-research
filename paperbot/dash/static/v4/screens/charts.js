// #/charts — 여러 차트 한 번에 (owners 10/06: "클릭이 너무 많다"): 2×2 or 3×3 candle charts on one screen. Each cell
// picks its coin and timeframe, and may lay one of our open positions on that coin over it (기존 36 · 5분봉 · 추가 계좌,
// or all of them; DeepSeek and coin flips are never offered: their money is shown only on their own group screens).
// The layout and every cell are remembered on this device (dom.js local, core/prefs.js GRID_KEY); the 설정 panel can
// change the layout and the cells' '선' choice while the screen is open.
// Charts: the same chart deck as the terminal (core/chartfx.js: the AI skin's glow, Premium / Discount light, a flash
// on a real big trade or our own fill of the cell's coin), in its `lite` form (the glow in one soft pass) so nine cells
// stay smooth. Data: /api/candles (300 bars per cell, then the forming bar of each coin + timeframe every 6 s, one
// request per distinct pair), the store's ticker for the prices, the board for the positions, and the server's
// market-trade relay through ONE connection for the whole screen (terminal-live.js tickStream: its trades move the
// forming candles of every cell of that coin, its large orders flash them). Every cell has '크게' and the key "f"
// (core/fullchart.js). HONESTY: every motion follows a real price, trade or fill; no cell animates by itself.
import {h, put, ui, fmt, store, local, bars, makeChart, candleOptions, tok, priceDec, chartDeck, chartAi, bigEvent, ownEvent,
  fullChart, onPref, setPref, GRID_KEY, GRID_DECK, GROUP_KO, deckState, motion} from "../core/pb.js";
import {tickStream} from "./terminal-live.js";
import {posLines} from "./chart-lines.js";
import {normPos, nameOf, reelExits} from "./positions-kit.js";

export const TFS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];
const SHORT = {"1m": "1분", "5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일"};
export const LAYOUTS = {"2x2": 4, "3x3": 9};
// the first cells of a new device: the six traded coins on 15분, then BTC / ETH on 1시간 and BTC on 4시간
export const DEFAULT_CELLS = [["BTCUSDT", "15m"], ["ETHUSDT", "15m"], ["SOLUSDT", "15m"], ["DOGEUSDT", "15m"], ["LTCUSDT", "15m"],
  ["BCHUSDT", "15m"], ["BTCUSDT", "1h"], ["ETHUSDT", "1h"], ["BTCUSDT", "4h"]].map(([sym, tf]) => ({sym, tf, acct: ""}));
const MAIN = new Set(["core", "m5", "extra"]);             // groups whose positions a cell may lay over its chart
const BARS = 300;
const POLL_MS = 6000;
const RELAY_FRESH_MS = 6000;

/** A stored grid -> a clean one: a known layout, nine cells of known coins / timeframes (a bad cell takes the default). */
export function cleanGrid(v) {
  const x = v && typeof v === "object" ? v : {};
  const cells = DEFAULT_CELLS.map((d, i) => {
    const c = Array.isArray(x.cells) && x.cells[i] && typeof x.cells[i] === "object" ? x.cells[i] : {};
    return {sym: bars.SYMS.includes(c.sym) ? c.sym : d.sym, tf: TFS.includes(c.tf) ? c.tf : d.tf,
      acct: typeof c.acct === "string" && c.acct.length < 80 ? c.acct : ""};
  });
  return {layout: Object.hasOwn(LAYOUTS, x.layout) ? x.layout : "2x2", cells};
}
/** The positions a cell may lay over its chart: our accounts (기존 36 · 5분봉 · 추가) with an open position on `sym`. */
export function overlayAccounts(board, sym) {
  return (board && Array.isArray(board.accounts) ? board.accounts : [])
    .filter((a) => a.position && a.position.symbol === sym && MAIN.has(fmt.groupOf(a)))
    .sort((a, b) => String(a.account_id).localeCompare(String(b.account_id)));
}

export async function mount(el, ctx) {
  ctx.setTitle("여러 차트");
  let cfg = cleanGrid(local.get(GRID_KEY, null));
  const save = () => local.set(GRID_KEY, cfg);
  const st = {board: null, cells: [], relay: "off"};

  // ---------------------------------------------------------------- the bar above the grid
  const laySeg = ui.seg([{id: "2x2", label: "2×2"}, {id: "3x3", label: "3×3"}], cfg.layout, (id) => setPref(GRID_KEY, {...cfg, layout: id}),
    {label: "칸 수"});
  const lineChips = h("div", {class: "cg-lines", role: "group", "aria-label": "모든 칸에 보일 선"});
  const paintChips = () => {
    const now = deckState(GRID_DECK.key, GRID_DECK.groups, GRID_DECK.defaults);
    put(lineChips, GRID_DECK.groups.map((g) => h("button", {type: "button", class: "cg-chip", "aria-pressed": String(!now.off.has(g)),
      onclick: () => {
        if (now.off.has(g)) now.off.delete(g); else now.off.add(g);
        setPref("cfx-" + GRID_DECK.key, {off: [...now.off], hide: [...now.hide].slice(-60)});
        paintChips();
      }}, GROUP_KO[g] || g)));
  };
  paintChips();
  const relayEl = h("span", {class: "cg-relay", dataset: {s: "off"}}, h("i", {"aria-hidden": "true"}), h("span", null, "시장 체결 연결 전"));
  const bar = h("div", {class: "cg-bar"},
    h("div", {class: "cg-bar-g"}, h("span", {class: "cg-k"}, "칸"), laySeg),
    h("div", {class: "cg-bar-g"}, h("span", {class: "cg-k"}, "선"), lineChips),
    h("span", {class: "grow"}), relayEl);
  const grid = h("div", {class: "cg-grid", dataset: {layout: cfg.layout}});
  const foot = h("div", {class: "cg-foot"},
    ui.note("칸마다 코인·봉·겹쳐 볼 포지션을 고르면 이 기기에 기억합니다. '크게' 또는 차트 위에서 f 키 = 크게 보기 (Esc로 돌아옴). ",
      chartAi() ? "빛·번쩍임은 바이낸스 실제 체결과 우리 봇 체결에만 반응합니다." : "빛·번쩍임은 AI 화면 색에서만 보입니다."),
    ui.assume("open", "포지션 선의 % = 그 포지션들의 미실현 ROE · 딥시크·동전 봇은 고를 수 없음"));
  el.append(ui.screenHead("여러 차트", "코인·봉을 칸마다 골라 한 화면에", h("a", {class: "btn-line", href: ctx.href("chart")}, "차트 하나 크게 →")),
    bar, grid, foot);

  // ---------------------------------------------------------------- one cell
  function cellOf(i) {
    const c = cfg.cells[i];
    const disposers = [];
    const sub = {                                   // the cell's own clean-up (a smaller layout removes it)
      track: (fn) => { if (typeof fn === "function") disposers.push(fn); return fn; },
      listen: (t, evt, fn, o) => { t.addEventListener(evt, fn, o); disposers.push(() => t.removeEventListener(evt, fn, o)); },
      alive: () => ctx.alive() && !cell.dead,
    };
    const symSel = h("select", {class: "select cg-sel", "aria-label": `칸 ${i + 1} 코인`}, bars.SYMS.map((s) => h("option", {value: s}, fmt.coin(s))));
    const tfSel = h("select", {class: "select cg-sel", "aria-label": `칸 ${i + 1} 봉`}, TFS.map((tf) => h("option", {value: tf}, SHORT[tf])));
    const ovSel = h("select", {class: "select cg-sel cg-ov", "aria-label": `칸 ${i + 1} 겹쳐 볼 포지션`});
    symSel.value = c.sym; tfSel.value = c.tf;
    const px = h("b", {class: "cg-px num"}, "—");
    const chg = h("small", {class: "cg-chg num"}, "");
    const fs = fullChart({ctx: sub, label: `칸 ${i + 1} 차트`});
    const legend = h("div", {class: "cg-legend num"});
    const box = h("div", {class: "cg-box"});
    const wrap = h("div", {class: "cg-wrap", "data-fc-grow": ""}, box, legend);
    const note = h("p", {class: "cg-note", hidden: true});
    const head = h("div", {class: "cg-h"}, symSel, tfSel, ovSel, h("span", {class: "grow"}), h("span", {class: "cg-pxw"}, px, chg), fs);
    const root = h("section", {class: "cg-cell", "aria-label": `칸 ${i + 1}`, dataset: {i: String(i)}}, head, wrap, note);
    fs.bind(root);
    const cell = {i, root, C: null, series: null, deck: null, last: null, loadTok: 0, relayAt: 0, dead: false, seenPos: null,
      get sym() { return cfg.cells[i].sym; }, get tf() { return cfg.cells[i].tf; }, get acct() { return cfg.cells[i].acct; }};

    function paintLegend(d) {
      if (!d) { legend.textContent = ""; return; }
      const ch = d.open ? (d.close - d.open) / d.open : null;
      put(legend, h("b", null, `${fmt.coin(cell.sym)} · ${SHORT[cell.tf]}`), ` 종 ${fmt.price(d.close)} `, h("span", {class: fmt.tone(ch)}, fmt.pct(ch, 2)));
    }
    function paintPrice() {
      const t = (store.get("ticker") || {})[cell.sym];
      const p = t ? (t.c ?? t.mark) : null;
      motion.tickPrice(px, p, p != null ? fmt.price(p) : "—", `cg${i}:${cell.sym}`);
      chg.textContent = t && t.p != null ? fmt.pct(Number(t.p) / 100, 2) : "";
      chg.className = "cg-chg num " + (t ? fmt.tone(t.p) : "");
    }
    function fillOverlay() {
      const list = overlayAccounts(st.board, cell.sym);
      const has = list.some((a) => a.account_id === cell.acct);
      const first = h("option", {value: ""}, !st.board ? "포지션 불러오는 중" : list.length ? `포지션 선 없음 · ${fmt.int(list.length)}개 열림` : "열린 우리 포지션 없음");
      const opts = list.length ? [h("option", {value: "all"}, `이 코인 우리 포지션 전부 (${fmt.int(list.length)}개)`),
        h("optgroup", {label: "한 계좌만"}, list.map((a) => { const p = normPos(a.position); return h("option", {value: a.account_id},
          `${nameOf(a)} · ${fmt.sideKo(p.side)} ${fmt.lev(p.leverage)}`); }))] : [];
      // a chosen account whose position has closed stays listed (so the choice is not lost silently) and says so
      const gone = cell.acct && cell.acct !== "all" && !has ? [h("option", {value: cell.acct}, `${fmt.idName(cell.acct)} · 포지션 닫힘`)] : [];
      ovSel.replaceChildren(first, ...opts, ...gone);
      ovSel.value = cell.acct === "all" && !list.length ? "" : cell.acct;
      ovSel.disabled = !list.length && !gone.length;
    }
    function drawLines() {
      if (!cell.deck) return;
      const list = overlayAccounts(st.board, cell.sym);
      const mark = store.mark(cell.sym);
      let accts = [];
      if (cell.acct === "all") accts = list;
      else if (cell.acct) accts = list.filter((a) => a.account_id === cell.acct);
      cell.deck.setLines("pos", posLines(accts, mark, {stops: cell.acct === "all" ? 3 : 2}));
      // the chosen account's liquidation price and the reel's target (one account only)
      const one = cell.acct && cell.acct !== "all" ? accts[0] : null;
      const p = one ? normPos(one.position) : null;
      const extra = [];
      if (p && p.liq) extra.push({id: `liq:${one.account_id}`, group: "risk", price: p.liq, tone: "warn", dash: 2, alpha: 0.55, axis: true, label: "청산가"});
      if (p && reelExits(one) && p.target) extra.push({id: `tp:${one.account_id}`, group: "risk", price: p.target, tone: "up", dash: 1, alpha: 0.55, axis: true, label: "목표"});
      cell.deck.setLines("acct", extra);
      note.textContent = cell.acct === "all" ? (list.length ? `우리 포지션 ${fmt.int(list.length)}개 · 선 이름표를 누르면 숨김` : "이 코인에 열린 우리 포지션이 지금 없습니다")
        : cell.acct ? (one ? `${nameOf(one)} · 진입 ${fmt.price(p.entry)}${p.liq ? ` · 청산가 ${fmt.price(p.liq)}` : ""}` : `${fmt.idName(cell.acct)}: 이 코인 포지션이 닫혔습니다`) : "";
      note.hidden = !note.textContent;
      // a position of this coin that is new since the last board: our bot really filled an entry (one accent flash)
      const keys = new Set(list.map((a) => a.account_id + "@" + (a.position.entry_time || a.position.entry_price || a.position.entry)));
      if (cell.seenPos && [...keys].some((k) => !cell.seenPos.has(k))) cell.deck.flash(ownEvent());
      if (st.board) cell.seenPos = keys;
    }
    async function load() {
      if (!cell.series) return;
      const tk = ++cell.loadTok, sym = cell.sym, tf = cell.tf;
      let data = [];
      try { data = await ctx.api(`/api/candles?symbol=${sym}&interval=${tf}&limit=${BARS}`); }
      catch (e) { if (e && e.name === "AbortError") return; note.textContent = "가격 자료를 불러오지 못했습니다 · 다음 갱신 때 다시"; note.hidden = false; }
      if (tk !== cell.loadTok || !sub.alive()) return;
      const dec = priceDec(data.length ? data[data.length - 1].close : store.mark(sym));
      cell.series.applyOptions({priceFormat: {type: "price", precision: dec, minMove: Math.pow(10, -dec)}});
      cell.deck.setData(data);
      cell.last = data[data.length - 1] || null;
      cell.relayAt = 0;
      paintLegend(cell.last);
      cell.deck.showRecent(cfg.layout === "3x3" ? 70 : 110, 8);
      drawLines();
    }
    function onCandles(rows) {                         // the poll's forming bar (and a new bar when one began)
      if (!cell.series || !cell.last) return;
      for (let x of rows || []) {
        if (x.time < cell.last.time) continue;
        if (x.time === cell.last.time && Date.now() - cell.relayAt < RELAY_FRESH_MS) {
          x = {...x, close: cell.last.close, high: Math.max(x.high, cell.last.high), low: Math.min(x.low, cell.last.low)};
        }
        if (cell.deck.update(x)) cell.last = x;
      }
      paintLegend(cell.last);
    }
    function onTick(ev) {                              // a real relay trade of this coin inside the bar on screen
      const p = Number(ev.p), t = Number(ev.t), span = bars.TF_MS[cell.tf];
      if (!cell.series || !cell.last || !Number.isFinite(p) || p <= 0 || !span) return;
      const t0 = cell.last.time * 1000;
      if (!(t >= t0 && t < t0 + span)) return;
      const x = {...cell.last, close: p, high: Math.max(cell.last.high, p), low: Math.min(cell.last.low, p)};
      if (!cell.deck.update(x)) return;
      cell.last = x; cell.relayAt = Date.now();
      paintLegend(cell.last);
    }

    symSel.addEventListener("change", () => { cfg.cells[i] = {...cfg.cells[i], sym: symSel.value, acct: ""}; save(); cell.seenPos = null; fillOverlay(); paintPrice(); load(); });
    tfSel.addEventListener("change", () => { cfg.cells[i] = {...cfg.cells[i], tf: tfSel.value}; save(); load(); });
    ovSel.addEventListener("change", () => { cfg.cells[i] = {...cfg.cells[i], acct: ovSel.value}; save(); drawLines(); });

    cell.ready = (async () => {
      try {
        const C = await makeChart(box, {rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.1, bottom: 0.08}},
          timeScale: {rightOffset: 8}, grid: {vertLines: {visible: false}, horzLines: {color: tok("--line")}}});
        if (cell.dead || !ctx.alive()) { C.dispose(); return; }
        cell.C = C;
        sub.track(C.dispose);
        cell.series = C.chart.addCandlestickSeries({...candleOptions(), lastValueVisible: true, priceLineVisible: true, priceLineStyle: 2, priceLineWidth: 1});
        cell.deck = chartDeck({chart: C.chart, series: cell.series, wrap, box, ctx: sub, key: GRID_DECK.key, groups: GRID_DECK.groups,
          defaults: GRID_DECK.defaults, lite: true, sym: () => cell.sym});
        C.chart.subscribeCrosshairMove((pt) => { const d = pt && pt.seriesData && pt.seriesData.get(cell.series); paintLegend(d || cell.last); });
      } catch (e) {
        put(box, h("div", {class: "cg-fail"}, ui.errorBox(e, () => location.reload())));
        return;
      }
      await load();
    })();
    fillOverlay(); paintPrice();
    cell.dispose = () => { cell.dead = true; for (const fn of disposers.splice(0).reverse()) { try { fn(); } catch (e) { console.error(e); } } root.remove(); };
    Object.assign(cell, {fillOverlay, drawLines, paintPrice, onCandles, onTick});
    return cell;
  }

  // ---------------------------------------------------------------- the grid
  function layout() {
    const n = LAYOUTS[cfg.layout];
    grid.dataset.layout = cfg.layout;
    laySeg.set(cfg.layout);
    while (st.cells.length > n) st.cells.pop().dispose();
    while (st.cells.length < n) { const c = cellOf(st.cells.length); st.cells.push(c); grid.append(c.root); }
  }
  ctx.track(() => { for (const c of st.cells.splice(0)) c.dispose(); });
  layout();
  // the 설정 panel (or this screen's own buttons) changed the layout or the cells' lines
  ctx.track(onPref(GRID_KEY, (v) => { const next = cleanGrid({...cfg, ...(v && typeof v === "object" ? v : {})}); if (next.layout !== cfg.layout) { cfg = {...cfg, layout: next.layout}; save(); layout(); } }));
  ctx.track(onPref("cfx-" + GRID_DECK.key, () => paintChips()));

  // ---------------------------------------------------------------- live data
  ctx.watch("ticker", () => { for (const c of st.cells) { c.paintPrice(); c.drawLines(); } });
  ctx.watch("board", (b) => { if (!b) return; st.board = b; for (const c of st.cells) { c.fillOverlay(); c.drawLines(); } });
  ctx.on("trades", (rows) => {
    for (const c of st.cells) {
      if ((rows || []).some((t) => t.symbol === c.sym && MAIN.has(fmt.SERVER_GROUP[t.group] || fmt.groupOf({kind: t.kind, timeframe: t.timeframe})))) c.deck && c.deck.flash(ownEvent());
    }
  });
  // the forming bar of every distinct coin + timeframe, one request each
  ctx.every(POLL_MS, async () => {
    const keys = [...new Set(st.cells.map((c) => `${c.sym}|${c.tf}`))];
    await Promise.all(keys.map(async (k) => {
      const [sym, tf] = k.split("|");
      try {
        const rows = await ctx.api(`/api/candles?symbol=${sym}&interval=${tf}&limit=2`);
        for (const c of st.cells) if (c.sym === sym && c.tf === tf) c.onCandles(rows);
      } catch (e) { /* the next poll */ }
    }));
  }, {now: false});
  // ONE relay connection for every cell (terminal-live.js tickStream): trades move the forming candles of that coin,
  // a new large order of that coin flashes its cells (the first message's rows are the past: no flash)
  const ticks = tickStream(ctx);
  ticks.on((m) => {
    if (m.state !== st.relay) {
      st.relay = m.state;
      relayEl.dataset.s = m.state;
      relayEl.lastChild.textContent = m.state === "live" ? "시장 체결 실시간" : m.state === "connecting" ? "시장 체결 연결 중" : m.state === "down" ? "시장 체결 끊김 · 5초 시세로" : "시장 체결 연결 전";
    }
    for (const ev of Array.isArray(m.ev) ? m.ev : []) {
      if (!ev || typeof ev.s !== "string") continue;
      for (const c of st.cells) if (c.sym === ev.s) c.onTick(ev);
    }
    if (!m.first && m.big && Array.isArray(m.big.rows)) {
      for (const r of m.big.rows) for (const c of st.cells) if (r && r.s === c.sym && c.deck) c.deck.flash(bigEvent(r));
    }
  });
  ticks.start();
  await Promise.all([store.need("board", 60000).catch(() => null), ...st.cells.map((c) => c.ready)]);
}

export function unmount() {}

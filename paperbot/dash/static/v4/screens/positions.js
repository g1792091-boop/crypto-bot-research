// #/positions — 포지션 (builder B, CONTRACT.md §4). Every open paper position as a calm card: a one-line row (side,
// coin, leverage, live unrealized P&L) that opens into the full card (LED P&L, why this leverage with the entry-time
// liquidation distance, entry / mark / liquidation / stop, a meter from now to the stop and the liquidation, the lock
// rule or the reel's own exits). Tabs 포지션 / 손절·잠금 주문 / 체결 기록 (closed trades with filters). A chosen coin
// shows its head and order book. Prices: /api/ticker through the store (5 s); nothing here can place an order.
import {h, ui, fmt, store, local, motion, serverNow} from "../core/pb.js";
import {normPos, posCard, tradeRow, tradeSum, coinSeg, reelExits, nameNode, dist, groupKo, sideCounts, oneSided, SKEW_MIN, SKEW_SHARE} from "./positions-kit.js";
import {coinHead, bookPanel} from "./positions-book.js";
import {riskLadder} from "./positions-risk.js";

const COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"];
const SORTS = [["pnl", "수익 큰 순"], ["loss", "손실 큰 순"], ["new", "최근 진입"], ["liq", "청산 가까운 순"]];
const GROUP_OPTS = [["", "모든 묶음"], ...fmt.GROUPS.map((g) => [g.id, g.ko])];
const TRADE_LIMIT = 1000;

export async function mount(el, ctx) {
  ctx.setTitle("포지션");
  // #/positions?coin=BTCUSDT (시장's funding rows): open on that coin, and remember it like a tap on its chip
  const qCoin = String((ctx.params.query || {}).coin || "").toUpperCase();
  if (COINS.includes(qCoin)) local.set("pos-sym", qCoin);
  const st = {
    sym: COINS.includes(qCoin) ? qCoin : local.get("pos-sym", ""), tab: local.get("pos-tab", "pos"), sort: local.get("pos-sort", "pnl"), grp: local.get("pos-grp", ""),
    tPer: local.get("pos-tper", "today"), tRes: "all", tGrp: "",
    board: null, why: {}, open: new Set(), firstOpen: true, trades: null, tradesErr: null, tradesDirty: true, countsKey: "",
  };
  const cards = new Map();            // account_id -> {key, el}: reused, so a number counts from its last value
  // 거래 채우기: at 1280 px and wider every card is open in a 2-3 column grid (v3 포지션); a phone keeps the accordion
  const wideMq = typeof matchMedia === "function" ? matchMedia("(min-width: 1280px)") : null;
  let wide = !!(wideMq && wideMq.matches);
  const markOf = (s) => store.mark(s);
  // price since the entry on each card: one /api/candles (5m, the last 24 h) per coin, asked when a card needs it
  // and again only after 5 minutes (never on a timer); the last point is the live mark the page already has
  const px = new Map();               // symbol -> {at, bars, busy}
  const PX_TTL = 5 * 60000;
  const needPx = (sym) => {
    const c = px.get(sym);
    if (c && (c.busy || Date.now() - c.at < PX_TTL)) return;
    px.set(sym, {...(c || {}), busy: true, at: c ? c.at : 0});
    ctx.api(`/api/candles?symbol=${encodeURIComponent(sym)}&interval=5m&limit=288`).then((bars) => {
      px.set(sym, {at: Date.now(), bars: Array.isArray(bars) ? bars : [], busy: false});
      if (ctx.alive()) for (const c2 of cards.values()) if (c2.el.pos.symbol === sym) sparkOf(c2.el);
    }).catch(() => { px.set(sym, {at: Date.now(), bars: (c && c.bars) || [], busy: false}); });
  };
  const sparkOf = (cardEl) => {
    const pos = cardEl.pos, c = px.get(pos.symbol);
    if (!c || !c.bars || !pos.entry_time) return;
    const t0 = Math.floor(pos.entry_time / 300000) * 300;
    const vals = c.bars.filter((b) => b.time >= t0).map((b) => b.close);
    if (pos.entry) vals.unshift(pos.entry);
    const m = markOf(pos.symbol);
    if (m) vals.push(m);
    if (vals.length >= 2) cardEl.setSpark(vals);
  };

  // ---------------------------------------------------------------- skeleton
  const sumNum = ui.liveNum(null, {dec: 2, sign: true, tone: true});
  const sumSub = h("span", {class: "s"}, "");
  const lsEl = h("b", null, "—"), nOpenSub = h("span", {class: "s"}, "");
  const line = h("p", {class: "positions-line"});
  const bestLine = h("div", {class: "positions-bw"});
  const sumCard = h("section", {class: "card positions-sum", "aria-label": "열린 포지션 요약"},
    h("div", {class: "stats"}, ui.stat("미실현 손익 합계 (USDT)", sumNum, sumSub), ui.stat("롱 · 숏", lsEl, nOpenSub)),
    line, ui.disclosure("가장 많이 버는·잃는 포지션", bestLine), ui.assume("open"));

  const coinBar = h("div", {class: "positions-coins-bar"});
  const tabBar = h("div", {class: "positions-tabs"});
  const tabBody = h("div", {class: "stack"});
  const side = h("div", {class: "stack positions-side"});
  const ladder = riskLadder(ctx);
  const sideBook = h("div", {class: "stack"});
  side.append(ladder.el, sideBook);
  el.append(ui.screenHead("포지션", "모의 계좌의 열린 포지션 · 주문 버튼 없음"), sumCard, coinBar,
    h("div", {class: "positions-cols"}, h("div", {class: "stack", dataset: {tour: "positions"}}, tabBar, tabBody), side));

  // ---------------------------------------------------------------- data helpers
  const positions = () => {
    const b = st.board;
    if (!b) return [];
    return b.accounts.filter((a) => a.position).map((a) => ({a, pos: normPos(a.position)}));
  };
  const inScope = (x) => (!st.sym || x.pos.symbol === st.sym) && (!st.grp || fmt.groupOf(x.a) === st.grp);
  const live = (x) => { const m = markOf(x.pos.symbol); if (!m) return null; return x.pos.side * x.pos.qty * (m - x.pos.entry); };
  const liqGap = (x) => { const m = markOf(x.pos.symbol); return m && x.pos.liq ? Math.abs(m - x.pos.liq) / m : 9; };
  const sorted = (list) => {
    const by = {
      pnl: (x, y) => (live(y) ?? -1e18) - (live(x) ?? -1e18),
      loss: (x, y) => (live(x) ?? 1e18) - (live(y) ?? 1e18),
      new: (x, y) => (y.pos.entry_time || 0) - (x.pos.entry_time || 0),
      liq: (x, y) => liqGap(x) - liqGap(y),
    };
    return [...list].sort(by[st.sort] || by.pnl);
  };

  // ---------------------------------------------------------------- the coin strip (counts of open positions)
  // each coin: long ↑ / short ↓ counts and a dot when one side holds 80 % or more of at least 5 (counts only, no money)
  const renderCoins = (all) => {
    const counts = {};
    const mine = all.filter((x) => !st.grp || fmt.groupOf(x.a) === st.grp);
    for (const x of mine) counts[x.pos.symbol] = (counts[x.pos.symbol] || 0) + 1;
    const sides = sideCounts(mine);
    const key = JSON.stringify([counts, sides, st.sym]);
    if (key === st.countsKey) return;
    st.countsKey = key;
    const skewed = COINS.some((c) => oneSided(sides[c]));
    coinBar.replaceChildren(coinSeg(COINS, counts, st.sym, (s) => { st.sym = s; local.set("pos-sym", s); renderAll(false); }, {label: "코인 고르기", sides}),
      h("p", {class: "pos-note positions-skew-note"}, "↑ 롱 · ↓ 숏 개수",
        skewed ? [" · ", h("i", {class: "pos-skew", "aria-hidden": "true"}), ` 한 방향 몰림 (${fmt.int(SKEW_MIN)}개 이상 중 한쪽 ${fmt.int(SKEW_SHARE * 100)}% 이상)`] : null));
  };

  // ---------------------------------------------------------------- summary (follows the coin and group filters)
  const renderSum = () => {
    const list = positions().filter(inScope);
    let tot = 0, known = 0, up = 0, dn = 0, mg = 0, best = null, worst = null;
    for (const x of list) {
      mg += x.pos.margin || 0;
      const u = live(x);
      if (u == null) continue;
      known++; tot += u;
      if (u > 0) up++; else if (u < 0) dn++;
      if (!best || u > best.u) best = {x, u};
      if (!worst || u < worst.u) worst = {x, u};
    }
    sumNum.update(known ? tot : null);
    sumSub.textContent = known && mg ? `묶인 증거금 대비 ${fmt.pct(tot / mg, 2)}` : "";
    sumSub.className = "s " + fmt.tone(tot);
    const longs = list.filter((x) => x.pos.side > 0).length;
    lsEl.textContent = `${fmt.int(longs)} · ${fmt.int(list.length - longs)}`;
    const scope = [st.sym ? fmt.coin(st.sym) : "", st.grp ? fmt.GROUP_KO[st.grp] : ""].filter(Boolean).join(" · ");
    nOpenSub.textContent = `열린 ${fmt.int(list.length)}개${scope ? " · " + scope : ""}`;
    line.replaceChildren("수익 중 ", h("b", {class: "up"}, fmt.int(up)), " · 손실 중 ", h("b", {class: "down"}, fmt.int(dn)),
      " · 묶인 증거금 ", h("b", {class: "num"}, fmt.usdt(mg)));
    const bw = (lab, b) => b ? h("a", {class: "positions-bwl", href: ctx.href("account", b.x.a.account_id)}, h("span", {class: "muted"}, lab),
      h("b", {class: "positions-bwn"}, nameNode(b.x.a)), h("span", {class: "muted"}, fmt.coin(b.x.pos.symbol)), h("b", {class: ["num", fmt.tone(b.u)]}, fmt.money(b.u, true))) : null;
    const byG = {};
    for (const x of list) { const g = groupKo(x.a); byG[g] = (byG[g] || 0) + 1; }
    bestLine.replaceChildren(bw("가장 많이 버는 중", best && best.u > 0 ? best : null), bw("가장 많이 잃는 중", worst && worst.u < 0 ? worst : null),
      list.length ? h("p", {class: "positions-groups muted"}, "묶음별 ", Object.entries(byG).map(([g, n]) => `${g} ${fmt.int(n)}`).join(" · ")) : null);
  };

  // ---------------------------------------------------------------- tab: 포지션 (cards, paged)
  const sortSel = h("select", {class: "select", "aria-label": "정렬"}, SORTS.map(([v, t]) => h("option", {value: v}, t)));
  sortSel.value = st.sort;
  sortSel.addEventListener("change", () => { st.sort = sortSel.value; local.set("pos-sort", st.sort); renderAll(false); });
  const grpSel = h("select", {class: "select", "aria-label": "묶음"}, GROUP_OPTS.map(([v, t]) => h("option", {value: v}, t)));
  grpSel.value = st.grp;
  grpSel.addEventListener("change", () => { st.grp = grpSel.value; local.set("pos-grp", st.grp); st.countsKey = ""; renderAll(false); });
  const cardOf = (x) => {
    const id = x.a.account_id, w = st.why[id];
    const key = [wide ? "w" : "n", x.pos.symbol, x.pos.entry_time, x.pos.stop, x.pos.lock_roe, x.pos.liq, x.pos.margin, x.pos.target, x.pos.timeExit,
      w ? `${w.entry_time}:${w.leverage}:${w.group}` : ""].join("|");
    let c = cards.get(id);
    if (!c || c.key !== key) {
      const elc = posCard(x.a, x.pos, {why: w, wallet: x.a.wallet, collapsible: true, open: wide || st.open.has(id), href: ctx.href, caption: !wide,
        onToggle: (aid, o) => { if (o) st.open.add(aid); else st.open.delete(aid); }});
      c = {key, el: elc};
      cards.set(id, c);
      elc.update(markOf(x.pos.symbol));
      sparkOf(elc);
    }
    needPx(x.pos.symbol);
    return c.el;
  };
  const posPager = ui.pager({size: wide ? 12 : 8, row: (x) => cardOf(x), empty: "조건에 맞는 열린 포지션이 없습니다"});
  const posNote = h("p", {class: "pos-note"});
  const notePos = () => { posNote.textContent = (wide ? "넓은 화면이라 모든 카드를 펼쳐 둡니다. " : "한 줄을 누르면 펼쳐집니다. ") + "미실현 손익은 마크 가격 기준이고 5초마다 서버 시세로 바뀝니다."; };
  notePos();
  const posPane = h("div", {class: "stack"}, h("div", {class: "row wrap positions-filters"}, grpSel, sortSel), posPager.el, posNote,
    ui.assume("open"));

  // ---------------------------------------------------------------- tab: 손절·잠금 주문
  const orderRow = (x) => {
    const m = markOf(x.pos.symbol), reel = reelExits(x.a);
    const pnl = x.pos.side * x.pos.qty * (x.pos.stop - x.pos.entry);
    const kind = reel ? "손절 · 스윙 저점 (스탑 마켓)" : x.pos.lock_roe != null ? `익절 잠금 +${fmt.num(x.pos.lock_roe * 100, 0)}% (스탑 마켓)` : "손절 (스탑 마켓)";
    return h("div", {class: "lrow click", role: "listitem", tabindex: "0", onclick: () => ctx.go("account", x.a.account_id),
      onkeydown: (e) => { if (e.key === "Enter") ctx.go("account", x.a.account_id); }},
      ui.sideTag(x.pos.side), h("span", {class: "lname", title: x.a.account_id}, nameNode(x.a)),
      h("span", {class: "ret num"}, fmt.price(x.pos.stop)),
      h("span", {class: "meta"}, h("span", null, `${fmt.coin(x.pos.symbol)} · ${fmt.lev(x.pos.leverage)}`), h("span", null, kind),
        h("span", null, `지금과 ${dist(m && x.pos.stop ? Math.abs(m - x.pos.stop) / m : null)}`),
        h("span", {class: fmt.tone(pnl)}, `발동 시 ${fmt.money(pnl, true)} USDT`),
        reel ? h("span", null, `목표 리밋 ${x.pos.target ? fmt.price(x.pos.target) : "받는 중"}`) : null));
  };
  const ordPager = ui.pager({size: 10, row: orderRow, empty: "걸려 있는 손절·잠금 주문이 없습니다"});
  const ordPane = h("div", {class: "stack"}, ordPager.el,
    h("p", {class: "pos-note"}, "가격 순서: 지금 가격과 가까운 주문이 위. 발동 시 손익은 나갈 때 수수료 전입니다. 모의 주문이라 거래소에는 아무것도 걸려 있지 않습니다."),
    ui.assume("open"));

  // ---------------------------------------------------------------- tab: 체결 기록 (closed trades, filters)
  const perSeg = ui.seg([{id: "today", label: "오늘"}, {id: "all", label: `최근 ${fmt.int(TRADE_LIMIT)}건`}], st.tPer,
    (v) => { st.tPer = v; local.set("pos-tper", v); renderTrades(true); }, {label: "기간"});
  const resSeg = ui.seg([{id: "all", label: "전부"}, {id: "win", label: "수익"}, {id: "loss", label: "손실"}, {id: "liq", label: "강제청산"}], st.tRes,
    (v) => { st.tRes = v; renderTrades(true); }, {label: "결과"});
  const tGrpSel = h("select", {class: "select", "aria-label": "묶음"}, GROUP_OPTS.map(([v, t]) => h("option", {value: v}, t)));
  tGrpSel.addEventListener("change", () => { st.tGrp = tGrpSel.value; renderTrades(true); });
  const tSum = h("div");
  const tNote = h("p", {class: "pos-note"});
  const acctOf = (id) => st.board && st.boardMap && st.boardMap.get(id);
  const tPager = ui.pager({size: 10, row: (t) => tradeRow(t, acctOf(t.account_id), {onClick: (r) => ctx.go("account", r.account_id),
    replay: t.id != null ? ctx.href("replay", String(t.id)) : null}),
    empty: "조건에 맞는 체결이 없습니다"});
  const trPane = h("div", {class: "stack"}, h("div", {class: "row wrap positions-filters"}, perSeg, resSeg, tGrpSel), tSum, tPager.el, tNote,
    ui.assume("closed", "손익은 나갈 때 수수료·펀딩 뒤"));

  async function loadTrades() {
    st.tradesDirty = false;
    if (!st.trades) tSum.replaceChildren(motion.shimmer(3));
    try {
      st.trades = await ctx.api(`/api/trades?limit=${TRADE_LIMIT}`);
      st.tradesErr = null;
    } catch (e) {
      if (e && e.name === "AbortError") return;
      st.tradesErr = e;
    }
    if (ctx.alive()) renderTrades(false);
  }
  function renderTrades(animate) {
    if (st.tradesErr && !st.trades) { tSum.replaceChildren(ui.errorBox(st.tradesErr, loadTrades)); return; }
    if (!st.trades) return;
    const day0 = fmt.kstMidnight(serverNow());
    let rows = st.trades;
    if (st.tPer === "today") rows = rows.filter((t) => t.exit_time >= day0);
    if (st.sym) rows = rows.filter((t) => t.symbol === st.sym);
    const g = st.tGrp;
    if (g) rows = rows.filter((t) => fmt.groupOf({kind: t.kind, timeframe: t.timeframe}) === g);
    if (st.tRes === "win") rows = rows.filter((t) => t.pnl > 0);
    else if (st.tRes === "loss") rows = rows.filter((t) => t.pnl < 0);
    else if (st.tRes === "liq") rows = rows.filter((t) => t.exit_reason === "LIQ");
    tSum.replaceChildren(tradeSum(rows));
    const oldest = st.trades[st.trades.length - 1];
    const cut = st.trades.length >= TRADE_LIMIT && oldest && (st.tPer !== "today" || oldest.exit_time >= day0);
    tNote.textContent = (st.tPer === "today" ? "오늘 = 한국 시각 0시부터. " : "") +
      (cut ? `거래가 많아 최근 ${fmt.int(TRADE_LIMIT)}건까지만 셉니다. ` : "") + "한 줄을 누르면 그 계좌로, '다시보기'는 그 거래를 봉 하나씩 다시 봅니다.";
    tPager.set(rows, !animate);
  }

  // ---------------------------------------------------------------- tabs
  const TABS = () => {
    const all = positions().filter(inScope);
    return [{id: "pos", label: `포지션 ${fmt.int(all.length)}`}, {id: "ord", label: "손절·잠금 주문"}, {id: "trd", label: "체결 기록"}];
  };
  let tabSeg = null, tabLabelKey = "";
  const renderTabBar = () => {
    const opts = TABS(), key = opts.map((o) => o.label).join("|");
    if (key === tabLabelKey) return;
    tabLabelKey = key;
    tabSeg = ui.seg(opts, st.tab, (v) => { st.tab = v; local.set("pos-tab", v); showTab(true); }, {label: "포지션 보기"});
    tabBar.replaceChildren(tabSeg);
  };
  const showTab = (animate) => {
    const pane = st.tab === "ord" ? ordPane : st.tab === "trd" ? trPane : posPane;
    if (tabBody.firstChild !== pane) tabBody.replaceChildren(pane);
    if (animate) motion.swap(tabBody);
    if (st.tab === "trd" && (st.tradesDirty || !st.trades)) loadTrades();
  };

  // ---------------------------------------------------------------- the side: one coin's head and order book
  // (the chosen coin; with 전체, the coin of the top position, or the one picked here)
  let head = null, book = null, bookSym = local.get("pos-book", "");
  const bookCoin = () => st.sym || bookSym || st.autoSym || COINS[0];     // autoSym: the coin of the card that opened first
  const bookSel = h("select", {class: "select", "aria-label": "호가 코인"}, COINS.map((c) => h("option", {value: c}, fmt.coin(c))));
  bookSel.addEventListener("change", () => { bookSym = bookSel.value; local.set("pos-book", bookSym); renderSide(); });
  let sideSym = null;
  const renderSide = () => {
    const sym = bookCoin();
    bookSel.value = sym;
    bookSel.hidden = !!st.sym;
    if (sym === sideSym && head) return;
    sideSym = sym;
    head = coinHead(sym, {chartHref: ctx.href("chart", sym)});
    if (!book) book = bookPanel(ctx, sym, {rows: 7}); else book.setSym(sym);
    sideBook.replaceChildren(ui.card({plate: "호가", acts: [bookSel]}, head, book));
    head.update(store.get("ticker"));
    book.load();
  };

  // ---------------------------------------------------------------- render everything
  function renderAll(keepPage) {
    const all = positions();
    st.boardMap = st.board ? new Map(st.board.accounts.map((a) => [a.account_id, a])) : new Map();
    renderCoins(all);
    renderTabBar();
    const list = sorted(all.filter(inScope));
    posPager.set(list, keepPage);
    const ords = all.filter(inScope).sort((x, y) => {
      const mx = markOf(x.pos.symbol), my = markOf(y.pos.symbol);
      return (mx ? Math.abs(mx - x.pos.stop) / mx : 9) - (my ? Math.abs(my - y.pos.stop) / my : 9);
    });
    ordPager.set(ords, keepPage);
    for (const id of [...cards.keys()]) if (!all.some((x) => x.a.account_id === id)) cards.delete(id);
    if (st.firstOpen && store.get("ticker") && list.length) {      // the top card starts open (once, sorted by live P&L)
      st.firstOpen = false;
      st.autoSym = list[0].pos.symbol;
      st.open.add(list[0].a.account_id);
      cards.delete(list[0].a.account_id);
      posPager.rerender();
    }
    renderSum();
    renderSide();
    ladder.set(all.filter(inScope), markOf);
    if (st.tab === "trd" && st.trades) renderTrades(false);
  }
  const onTicker = (tk) => {
    for (const c of cards.values()) if (c.el.isConnected) { c.el.update(markOf(c.el.pos.symbol)); sparkOf(c.el); }
    if (st.firstOpen && st.board) renderAll(true);
    renderSum();
    if (st.board) ladder.set(positions().filter(inScope), markOf);
    if (head) head.update(tk);
  };

  // ---------------------------------------------------------------- wiring
  const onWide = () => {
    const w = !!(wideMq && wideMq.matches);
    if (w === wide) return;
    wide = w;
    el.classList.toggle("positions-wide", wide);
    notePos();
    renderAll(true);
  };
  el.classList.toggle("positions-wide", wide);
  if (wideMq) { wideMq.addEventListener("change", onWide); ctx.track(() => wideMq.removeEventListener("change", onWide)); }
  renderTabBar();
  showTab(false);
  renderSide();
  ctx.watch("board", (b) => {
    if (!b) return;
    st.board = b;
    renderAll(true);
  });
  ctx.watch("levwhy", (w) => { if (w && w.positions) { st.why = w.positions; if (st.board) renderAll(true); } });
  ctx.watch("ticker", (tk) => { if (tk) onTicker(tk); });
  ctx.every(1000, () => { if (head) head.tick(); }, {now: false});
  let tT = null;
  ctx.on("trades", () => {
    st.tradesDirty = true;
    if (st.tab !== "trd") return;
    clearTimeout(tT);
    tT = setTimeout(() => { if (ctx.alive()) loadTrades(); }, 1500);
  });
  ctx.track(() => clearTimeout(tT));
  // first paint: wait for the board (shimmer meanwhile; the router fades the screen in after this)
  await store.need("board", 60000).catch(() => null);
}

export function unmount() {}

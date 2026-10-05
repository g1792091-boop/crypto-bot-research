// chart (builder B): the panels under the chart (beside it on a PC), as tabs: this coin's positions, its closed
// trades, its signals, the order book, market liquidations (only while the liquidation recorder runs) and price
// alerts. Each pane loads when it is first shown and follows the chart's coin.
import {h, ui, fmt, store, local, motion, features} from "../core/pb.js";
import {normPos, tradeRow, nameNode} from "./positions-kit.js";
import {bookPanel} from "./positions-book.js";
import {alertsPane} from "./chart-alerts.js";

const STATUS_KO = {SUBMITTED: "진입 요청", RECORD: "기록만", LATE: "늦음 (진입 안 함)", NO_PRICE: "가격 없음", NO_ATR: "ATR 없음"};

/**
 * sidePanels(ctx, {sym, onPick(account_id), onAlerts(data)}) -> element with .setSym(sym), .onTicker(), .onBoard(b),
 * .onTrades().
 */
export function sidePanels(ctx, o) {
  let sym = o.sym, board = null;
  let tab = local.get("chart-tab", "pos");
  const body = h("div", {class: "stack"});
  const tabsEl = h("div");
  const el = h("section", {class: "card chart-panels", "aria-label": "이 코인 자세히"}, tabsEl, body);
  const panes = {};

  // ---------------------------------------------------------------- this coin's open positions
  const posRow = (x) => {
    const m = store.mark(x.pos.symbol);
    const roe = m ? (x.pos.side * x.pos.qty * (m - x.pos.entry)) / x.pos.margin : null;
    const lock = x.pos.lock_roe != null && !(x.a.kind === "reel" || (x.a.kind === "random" && x.a.timeframe === "5m"));
    return h("div", {class: "lrow click", role: "listitem", tabindex: "0", title: "차트에 이 계좌 진입·청산 표시",
      onclick: () => o.onPick(x.a.account_id), onkeydown: (e) => { if (e.key === "Enter") o.onPick(x.a.account_id); }},
      ui.sideTag(x.pos.side), h("span", {class: "lname"}, nameNode(x.a)),
      h("span", {class: ["ret", "num", fmt.tone(roe)]}, roe == null ? "—" : fmt.pct(roe)),
      h("span", {class: "meta"}, h("span", null, fmt.lev(x.pos.leverage)), h("span", null, `진입 ${fmt.price(x.pos.entry)}`),
        h("span", {class: lock ? "up" : ""}, lock ? `잠금 +${fmt.num(x.pos.lock_roe * 100, 0)}% ${fmt.price(x.pos.stop)}` : `손절 ${fmt.price(x.pos.stop)}`),
        h("a", {href: ctx.href("account", x.a.account_id), onclick: (e) => e.stopPropagation()}, "계좌")));
  };
  const mine = () => ((board && board.accounts) || []).filter((a) => a.position && a.position.symbol === sym).map((a) => ({a, pos: normPos(a.position)}));
  const makePos = () => {
    const pg = ui.pager({size: 10, row: posRow, empty: "이 코인에 열린 포지션이 없습니다"});
    const pane = h("div", {class: "stack tight"}, h("p", {class: "pos-note"}, "누르면 차트에 그 계좌의 진입·청산과 손절선이 나옵니다. ROE는 마크 가격 기준."), pg.el,
      ui.assume("open"));
    pane.refresh = (keep) => pg.set(mine().sort((x, y) => (y.pos.entry_time || 0) - (x.pos.entry_time || 0)), keep);
    pane.refresh(false);
    return pane;
  };

  // ---------------------------------------------------------------- this coin's closed trades
  const makeTrades = () => {
    const pg = ui.pager({size: 10, row: (t) => tradeRow(t, board && board.accounts.find((a) => a.account_id === t.account_id),
      {onClick: (r) => ctx.go("account", r.account_id)}), empty: "이 코인 체결이 아직 없습니다"});
    const sum = h("div");
    const pane = h("div", {class: "stack tight"}, sum, pg.el, ui.assume());
    let mySym = null;
    pane.refresh = async () => {
      const want = sym;
      if (mySym !== want) { sum.replaceChildren(motion.shimmer(2)); pg.set([]); }
      try {
        const rows = await ctx.api(`/api/trades?symbol=${encodeURIComponent(want)}&limit=100`);
        if (want !== sym || !ctx.alive()) return;
        sum.replaceChildren(h("p", {class: "pos-sum"}, `최근 ${fmt.int(rows.length)}건 (이 코인, 모든 계좌)`));
        pg.set(rows, mySym === want);
        mySym = want;
      } catch (e) { if (!(e && e.name === "AbortError")) sum.replaceChildren(ui.errorBox(e, pane.refresh)); }
    };
    pane.refresh();
    return pane;
  };

  // ---------------------------------------------------------------- this coin's signals
  const sigRow = (r) => h("div", {class: "lrow", role: "listitem"},
    h("span", {class: "rk"}, fmt.kst(r.bar_close)), h("span", {class: "lname"}, fmt.stratKo(r.strategy)),
    h("span", {class: "ret"}, ui.sideTag(r.side)),
    h("span", {class: "meta"}, h("span", null, fmt.tfKo(r.timeframe)), h("span", {class: r.status === "LATE" ? "warn-t" : ""}, STATUS_KO[r.status] || r.status),
      h("span", null, r.delay_ms == null ? "지연 —" : `지연 ${fmt.num(r.delay_ms / 1000, 1)}초`), r.ref_price ? h("span", null, `기준가 ${fmt.price(r.ref_price)}`) : null));
  const makeSignals = () => {
    const pg = ui.pager({size: 10, row: sigRow, empty: "이 코인 신호가 없습니다"});
    const head = h("div");
    const pane = h("div", {class: "stack tight"}, head, pg.el);
    pane.refresh = async () => {
      const want = sym;
      head.replaceChildren(motion.shimmer(2));
      try {
        const rows = await ctx.api(`/api/signals?symbol=${encodeURIComponent(want)}&limit=150`);
        if (want !== sym || !ctx.alive()) return;
        head.replaceChildren(h("p", {class: "pos-sum"}, `최근 신호 ${fmt.int(rows.length)}개 · 봉 마감 시각 기준`));
        pg.set(rows);
      } catch (e) { if (!(e && e.name === "AbortError")) head.replaceChildren(ui.errorBox(e, pane.refresh)); }
    };
    pane.refresh();
    return pane;
  };

  // ---------------------------------------------------------------- market liquidations (feature: the recorder runs)
  const usdK = (x) => (x >= 1e6 ? `${fmt.num(x / 1e6, 2)}M` : x >= 1e3 ? `${fmt.num(x / 1e3, 1)}K` : fmt.num(x, 0));
  const makeLiq = () => {
    const box = h("div", {class: "stack tight"}, motion.shimmer(3));
    const pane = h("div", {class: "stack tight"}, box);
    let busy = false;
    pane.refresh = async () => {
      if (busy || !pane.isConnected) return;
      busy = true;
      const want = sym;
      try {
        const d = await ctx.api(`/api/liq?symbol=${encodeURIComponent(want)}&minutes=60`);
        if (want !== sym || !ctx.alive()) return;
        if (!d.recorder) { box.replaceChildren(ui.empty("강제청산 기록기 자료가 없습니다")); return; }
        const tot = (d.long_usd || 0) + (d.short_usd || 0), share = tot > 0 ? d.long_usd / tot : 0.5;
        const quiet = d.last_any ? Math.floor((Date.now() - d.last_any) / 60000) : null;
        box.replaceChildren(
          quiet != null && quiet >= 10 ? h("p", {class: "chart-warn"}, `기록기가 ${fmt.int(quiet)}분째 조용합니다. 아래는 그 전까지의 기록입니다.`) : null,
          h("p", {class: "pos-sum"}, `최근 1시간 ${fmt.coin(d.symbol)} 강제청산 (바이낸스 전체, ${fmt.int(d.n || 0)}건, 달러)`),
          h("div", {class: "pos-bkbar"}, h("span", {class: "down num"}, `롱 ${usdK(d.long_usd || 0)}`), h("div", {class: "chart-liqbar"}, h("i", {style: {width: (share * 100).toFixed(1) + "%"}})),
            h("span", {class: "up num"}, `숏 ${usdK(d.short_usd || 0)}`)),
          ...(d.rows || []).slice(0, 12).map((r) => h("div", {class: "lrow"}, h("span", {class: "rk"}, fmt.hm(r.ts)),
            h("span", {class: ["lname", r.liquidated === "long" ? "down" : "up"]}, r.liquidated === "long" ? "롱 청산" : "숏 청산"),
            h("span", {class: "ret num"}, usdK(r.usd)), h("span", {class: "meta"}, `가격 ${fmt.price(r.price)}`))),
          (d.rows || []).length ? null : ui.empty("최근 1시간 기록 없음"),
          h("p", {class: "pos-note"}, "롱 청산 = 롱 포지션이 강제로 정리됨 (가격 하락 쪽). 바이낸스가 코인마다 1초에 1건만 알려 줘서 실제보다 적게 잡힙니다."));
      } catch (e) { if (!(e && e.name === "AbortError")) box.replaceChildren(ui.errorBox(e, pane.refresh)); }
      finally { busy = false; }
    };
    pane.refresh();
    ctx.every(10000, () => { if (tab === "liq") pane.refresh(); }, {now: false});
    return pane;
  };

  // ---------------------------------------------------------------- tabs
  const TABS = () => [{id: "pos", label: `이 코인 포지션 ${fmt.int(mine().length)}`}, {id: "trd", label: "체결"}, {id: "sig", label: "신호"},
    {id: "book", label: "호가"}, features.liq ? {id: "liq", label: "시장 강제청산"} : null, {id: "al", label: "가격 알림"}].filter(Boolean);
  const make = {pos: makePos, trd: makeTrades, sig: makeSignals, book: () => { const b = bookPanel(ctx, sym, {rows: 8}); b.refresh = () => b.load(); return b; },
    liq: makeLiq, al: () => { const a = alertsPane(ctx, {sym, onData: o.onAlerts}); a.refresh = () => a.load(); a.load(); return a; }};
  let tabKey = "";
  const renderTabs = () => {
    const opts = TABS();
    if (!opts.some((x) => x.id === tab)) tab = "pos";
    const key = opts.map((x) => x.label).join("|") + tab;
    if (key === tabKey) return;
    tabKey = key;
    tabsEl.replaceChildren(ui.seg(opts, tab, (v) => { tab = v; local.set("chart-tab", v); tabKey = ""; renderTabs(); show(true); }, {label: "패널", scroll: true}));
  };
  const show = (animate) => {
    if (!panes[tab]) panes[tab] = make[tab]();
    const p = panes[tab];
    if (body.firstChild !== p) body.replaceChildren(p);
    if (p.symShown !== sym) { p.symShown = sym; if (p.setSym) p.setSym(sym); if (p.refresh && p.created) p.refresh(); }
    p.created = true;
    if (tab === "book" || tab === "liq") p.refresh();
    if (animate) motion.swap(body);
  };
  el.setSym = (s) => {
    if (s === sym) return;
    sym = s;
    for (const [k, p] of Object.entries(panes)) if (k !== tab) p.symShown = null;
    tabKey = ""; renderTabs(); show(false);
  };
  el.onBoard = (b) => { board = b; renderTabs(); if (panes.pos) panes.pos.refresh(true); };
  el.onTicker = () => { if (panes.pos && tab === "pos") panes.pos.refresh(true); if (panes.al) panes.al.tick(); };
  el.onTrades = (rows) => { if (panes.trd && (rows || []).some((t) => t.symbol === sym)) panes.trd.refresh(); };
  el.onFeatures = () => { tabKey = ""; renderTabs(); };
  el.alerts = () => { if (!panes.al) panes.al = make.al(); return panes.al; };
  renderTabs();
  show(false);
  return el;
}

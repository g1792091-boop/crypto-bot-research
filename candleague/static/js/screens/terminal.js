// #/terminal 터미널 — the rule bot's v4 터미널 (paperbot/dash/static/v4/screens/terminal*.js, copied and adapted; nothing
// imported from it), with the 후보 리그's own data. One screen without page scroll on a PC (stacked on a phone):
//   top     the coin, its big price, 24 h change, 거래대금, 마크, 펀딩 / 다음까지, 미결제약정, 24 h range, our positions
//           on it, the price feed's state, the bar-close countdown, the KST clock; the band "후보 리그 지금" (engine,
//           D+n and the next checkpoint, open positions, 후보 미실현, today's 후보 trades, "엔진 기준 HH:MM"); a banner
//           while the engine replays from 10/01 or has stopped (then no live P&L anywhere)
//   left    고른 포지션 (the selected account and its open position: 미실현 / ROE, prices, size, margin, 왜 N배, its five
//           accounts) and 우리 봇 체결 (entries and exits as they come, the recent long / short bar)
//   centre  the six coins (price, change, 롱 n · 숏 n, the crowding dot), the chart (1분 ~ 4시간; the selected
//           position's entry / stop / take-profit / liquidation lines, chips for up to five positions of this coin) and
//           the table of our positions (포지션 · 체결 · 손절 주문, the 묶음 select, long / short bar, 미실현 합계)
//   right   이 코인 포지션 (live ROE) and the 후보 accounts' 수익 차트 (realized) with 오늘 수익 and the 수익 캘린더
// The first position shown is an open 후보 position (the nearest to liquidation, else the biggest |P&L|, else the
// newest); ?acct=&coin=&tf=&at= (from 포지션, 체결 기록, 순위표, 계좌, 찾기) pick an account, a coin, a timeframe, a trade.
// Data: the page's /api/live (5 s), /api/positions (30 s and on every new engine snapshot), /api/fills (30 s),
// /api/klines, /api/trades/<id>, /api/pnl. 설치 뒤 진입만 (js/after.js, the switch over the band): on, the positions, the
// fills and the selected account's trades are filtered here, before any part sees them (side list, table, chart chips
// and marks, the band's counts; the feed filters its events itself, it keeps a history); the raw answers are kept and
// filtered again when the install time first becomes known (a cold load whose /api/fills answered before the snapshot
// and the positions did) or changes. The 수익 차트 (realized, the wallet's record) stays whole. Paper only: no order
// buttons. D11: hidden DeepSeek money is never shown
// (count-only rows, chips, feed lines; the sums leave them out and say so). The rule bot's market-wide panels (big
// trades, liquidations, order book, movers, the AI meeting line) have no data source here: left out, never faked.
import {h, local} from "../dom.js";
import * as LK from "../lk.js";
import {liveOk, livePnl, inGroup, POS_GROUPS} from "../poskit.js";
import {markOf} from "../live.js";
import {fadeIn} from "../v4kit.js";
import {COINS} from "../labels.js";
import {topBar} from "./terminal-top.js";
import {coinStrip, fillsFeed} from "./terminal-feed.js";
import {termChart} from "./terminal-chart.js";
import {bottomTable} from "./terminal-table.js";
import {selPanel, coinPositions, pnlPanel} from "./terminal-side.js";
import {ages, FOOT, TFS, hiddenPos} from "./terminal-kit.js";
import {afterPositions, afterFills, afterBook, afterOn, installMs} from "../after.js";

export const css = "scr/terminal.css";
export const wide = true;

/** The position the terminal opens on: an open 후보 position of the shown ones (nearest to liquidation when live numbers
 *  are allowed and known, else the biggest |P&L|, else the closest to liquidation at entry, else the newest); any shown
 *  position when no 후보 one is open; null when none. ``coin`` limits it to one coin. */
export function defaultPosition(doc, coin = null, group = "cand") {
  if (!doc || doc.status) return null;
  const shown = (doc.positions || []).filter((p) => !hiddenPos(p) && (!coin || p.coin === coin));
  const pool = [shown.filter((p) => p.role === "cand"), shown.filter((p) => inGroup(p, group)), shown].find((x) => x.length);
  if (!pool) return null;
  if (liveOk(doc)) {
    const xs = pool.map((p) => ({p, u: livePnl(p, markOf(p.coin))})).filter((x) => x.u);
    const near = xs.filter((x) => x.u.liqGap != null && x.u.liqGap > 0).sort((a, b) => a.u.liqGap - b.u.liqGap);
    if (near.length) return near[0].p;
    if (xs.length) return xs.sort((a, b) => Math.abs(b.u.pnl) - Math.abs(a.u.pnl))[0].p;
  }
  const byLiq = pool.filter((p) => p.liq_dist_entry != null).sort((a, b) => a.liq_dist_entry - b.liq_dist_entry);
  if (byLiq.length) return byLiq[0];
  return pool.slice().sort((a, b) => (b.since || 0) - (a.since || 0))[0];
}

export async function mount(el, ctx) {
  try { await ctx.meta(); } catch (e) { /* the codes stand in for the Korean names */ }
  if (!ctx.alive()) return undefined;
  const q = ctx.params.query || {};
  const savedGrp = local.get("tm-grp", "cand");
  const st = {
    coin: COINS.includes(q.coin) ? q.coin : COINS.includes(local.get("tm-coin", "")) ? local.get("tm-coin", "") : "BTCUSD",
    tf: TFS.includes(q.tf) ? q.tf : TFS.includes(local.get("tm-tf", "")) ? local.get("tm-tf", "") : "15m",
    sel: q.acct || null, at: q.at && Number.isFinite(Number(q.at)) ? Number(q.at) : null,
    grp: POS_GROUPS.some((g) => g.id === savedGrp) ? savedGrp : "cand",
    pos: null, book: null, fills: null,
  };
  const asked = {acct: !!q.acct, coin: COINS.includes(q.coin), tf: TFS.includes(q.tf)};
  const selAcct = () => (st.sel ? LK.index().byId[st.sel] || null : null);
  const selPos = () => (st.sel && st.pos && !st.pos.status ? (st.pos.positions || []).find((p) => p.id === st.sel) || null : null);
  const save = () => ctx.setQuery(Object.fromEntries(Object.entries({acct: st.sel, coin: st.coin, tf: st.tf}).filter(([, v]) => v)));

  // ---------------------------------------------------------------- the parts
  const top = topBar(ctx, st);
  const strip = coinStrip(ctx, st, (c) => pickCoin(c));
  const feed = fillsFeed(ctx, st, (x) => pickTrade(x));
  const sel = selPanel(ctx, st, {selAcct, selPos, book: () => st.book, doc: () => st.pos});
  const chart = termChart(ctx, st, {onTf: (tf) => setTf(tf), onPick: (id) => pickPos(id), selPos, selAcct, book: () => st.book});
  const table = bottomTable(ctx, st, {onPick: (id) => pickPos(id), onCoin: (c) => pickCoin(c), onGroup: (g) => setGroup(g), onTrade: (x) => pickTrade(x)});
  const mine = coinPositions(ctx, st, (id) => pickPos(id));
  const pnl = pnlPanel(ctx);
  const left = h("aside", {class: "tm-col tm-left", "aria-label": "고른 포지션과 우리 봇 체결"}, sel.el, feed.el);
  const mid = h("div", {class: "tm-mid"}, strip.el, chart.el, table.el);
  const right = h("aside", {class: "tm-col tm-right", "aria-label": "이 코인 포지션과 수익"}, mine.el, pnl.el);
  const root = h("div", {class: "tm"}, top.el, h("div", {class: "tm-grid"}, left, mid, right), h("p", {class: "tm-foot"}, FOOT));
  el.append(h("h1", {class: "tm-sr"}, "터미널"), root);

  // the screen fills the window under the menu on a PC (the menu's height differs with 글자 크기 and 메뉴 위치)
  const fit = () => { const y = root.getBoundingClientRect ? root.getBoundingClientRect().top + (window.scrollY || 0) : 0; root.style.setProperty("--tm-y", `${Math.round(y)}px`); };
  fit();
  window.addEventListener("resize", fit);
  const still = () => { root.dataset.still = document.hidden ? "1" : ""; };
  still();
  document.addEventListener("visibilitychange", still);

  // ---------------------------------------------------------------- picking
  function coinChanged() {
    local.set("tm-coin", st.coin);
    top.setCoin(); strip.setCoin(st.coin); chart.setCoin(); mine.setCoin(); table.setCoin();
  }
  function selChanged() {
    chart.setSel(); table.setSel(); mine.setSel(); sel.paint();
    loadBook();
  }
  function pickCoin(c) {
    if (!COINS.includes(c) || c === st.coin) return;
    st.coin = c; st.at = null;
    const p = selPos();
    if (!p || p.coin !== c) {
      const d = defaultPosition(st.pos, c, st.grp);
      if (d) st.sel = d.id;
    }
    coinChanged(); selChanged(); save();
  }
  function pickPos(id) {
    if (!id) return;
    const was = st.coin;
    st.sel = id; st.at = null;
    const p = selPos();
    if (p && p.coin !== st.coin) st.coin = p.coin;
    if (st.coin !== was) coinChanged();
    selChanged(); save();
  }
  function pickTrade(x) {
    if (!x || !x.account) return;
    const was = st.coin;
    st.sel = x.account;
    st.at = x.at || null;
    if (x.coin && COINS.includes(x.coin)) st.coin = x.coin;
    if (st.coin !== was) coinChanged(); else chart.reload();
    selChanged(); save();
  }
  function setTf(tf) {
    if (!TFS.includes(tf) || tf === st.tf) return;
    st.tf = tf; st.at = null; local.set("tm-tf", tf);
    chart.setTf(tf); top.tick(); save();
  }
  function setGroup(g) {
    if (!POS_GROUPS.some((x) => x.id === g)) return;
    st.grp = g; local.set("tm-grp", g);
    table.setGroup(); strip.repaint(); feed.repaint(); mine.onPositions(st.pos); chart.onPositions(st.pos); top.setGroup();
  }

  // ---------------------------------------------------------------- data
  // 설치 뒤 진입만: the cut the shown fills / trades were filtered with (null: not filtered); the raw answers stay so
  // that a cut known only later (the snapshot or the positions answered after /api/fills) filters them again
  const cutNow = () => (afterOn() ? installMs() : null);
  let rawFills = null, fillsCut = null, rawBook = null, bookCut = null, seenCut = null;
  function recut() {
    const k = cutNow();
    if (rawFills && k !== fillsCut) { fillsCut = k; st.fills = afterFills(rawFills); table.onFills(st.fills, rawFills); top.onFills(st.fills); }
    if (rawBook && k !== bookCut) { bookCut = k; st.book = {...afterBook(rawBook.b), id: rawBook.id}; chart.onBook(); sel.paint(); }
    if (k !== seenCut) { seenCut = k; feed.repaint(); }
  }
  let bookTok = 0;
  // a link to an account (?acct=) without a coin: the coin of its open position, else of its newest closed trade
  let coinFromBook = asked.acct && !asked.coin;
  async function loadBook() {
    const id = st.sel, tk = ++bookTok;
    if (!id) { st.book = null; return; }
    try {
      const b = await ctx.api(`/api/trades/${encodeURIComponent(id)}`);
      if (tk !== bookTok || !ctx.alive()) return;
      rawBook = {b, id};
      bookCut = cutNow();
      st.book = {...afterBook(b), id};                     // 설치 뒤 진입만: its trades (the chart marks, 마지막 거래)
    } catch (e) { return; }
    if (coinFromBook && st.pos) {
      coinFromBook = false;
      const t = st.book.trades && st.book.trades[0];
      const c = t ? String(t.symbol || "").replace(/T$/, "") : null;
      if (!selPos() && c && COINS.includes(c) && c !== st.coin) { st.coin = c; coinChanged(); save(); }
    }
    chart.onBook(); sel.paint();
  }
  async function loadFills() {
    let rows = null;
    try { rows = ((await ctx.api("/api/fills")) || {}).fills || []; } catch (e) { if (e && e.name === "AbortError") return; }
    if (!ctx.alive()) return;
    if (rows) { rawFills = rows; fillsCut = cutNow(); st.fills = afterFills(rows); }   // 설치 뒤 진입만: entered after the install
    feed.onFills(rows); table.onFills(rows ? st.fills : null, rawFills); top.onFills(st.fills);
  }

  let firstPos = true, lastGen = null;
  ctx.onPositions((d0) => {
    const d = afterPositions(d0);                          // 설치 뒤 진입만: every part reads these positions
    st.pos = d;
    top.onAfter(d0);
    if (firstPos && d && !d.status) {
      firstPos = false;
      if (!st.sel) {
        const p = defaultPosition(d, asked.coin ? st.coin : null, st.grp);
        if (p) { st.sel = p.id; if (!asked.coin && p.coin !== st.coin) { st.coin = p.coin; coinChanged(); } }
      } else if (!asked.coin) {
        const p = selPos();
        if (p && p.coin !== st.coin) { st.coin = p.coin; coinChanged(); }
      }
      save();
      loadBook();
    }
    top.onPositions(d); strip.onPositions(d); feed.onPositions(d); chart.onPositions(d); table.onPositions(d); mine.onPositions(d); sel.refresh();
    recut();
    const gen = d && d.generated_ms;
    if (gen && gen !== lastGen) {
      const again = lastGen != null;
      lastGen = gen;
      pnl.onSnap(gen);
      if (again) { loadFills(); loadBook(); }
    }
  });
  let tfFromAcct = asked.tf;
  ctx.onLeague(() => {
    const a = selAcct();
    if (a && !tfFromAcct && asked.acct) {           // a link to an account without a timeframe: that account's own
      tfFromAcct = true;
      if (a.tf && a.tf !== st.tf) { st.tf = a.tf; chart.setTf(a.tf); save(); }
    }
    top.onLeague(); sel.refresh(); feed.repaint(); table.setSel(); mine.setSel();
    recut();
  });
  ctx.onLive(() => { top.onLive(); strip.onLive(); chart.onLive(); table.onLive(); mine.onLive(); sel.refresh(); });
  ctx.every(30000, loadFills);
  ctx.every(120000, () => pnl.load());
  ctx.every(1000, () => { top.tick(); chart.tick(); ages(root); });
  top.tick(); coinChanged();

  const cleanup = () => {
    window.removeEventListener("resize", fit);
    document.removeEventListener("visibilitychange", still);
    chart.dispose();
  };
  await Promise.all([loadFills(), st.sel ? loadBook() : null, chart.ready]);
  // left while the chart loaded: the shell runs the returned cleanup at once (the chart, its listeners and observer go)
  if (!ctx.alive()) return cleanup;
  fit();
  fadeIn(root, 240);
  return cleanup;
}

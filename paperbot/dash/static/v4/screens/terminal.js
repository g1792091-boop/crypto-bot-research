// #/terminal — 터미널 (wave 2, the PC one-screen view; term v2 10/06: the owners' HelloQuant reference, "읽기 편하게").
// One screen, no page scroll on a PC:
//   top     the coin, its big price, 24 h change and quote volume, funding and the time to it, 급등 · 급락 · 음펀비 of
//           the whole Binance USD-M market (labelled 시장 전체), the KST clock; a slow line of the latest real AI
//           meeting conclusions under it;
//   left    three stacked dense lists, each with its ratio bar beneath (no switch): 실시간 큰 체결 (the whole market's
//           large orders, the server's relay), 시장 강제청산 (the chosen coin, while the recorder runs), 우리 봇 체결;
//   centre  the coin strip (7 coins, live), the chart (terminal-chart.js, unchanged), the positions table (ALL filter,
//           long / short share, open count, unrealized total);
//   right   이 코인 포지션 (with the order book behind a 호가 switch; no order buttons), 수익 차트 of 기존 36 (realized,
//           참고) with 오늘 수익 and the 수익 캘린더.
// Data: the same routes and the same cadence as 차트 / 포지션 / 시장 / 흐름 (store ticker 5 s, forming bar 5 s, book
// 3 s, liquidations 10 s, levels 2 min, GH Coin / calendar 5 min) plus /api/v4/movers once a minute (the server's own
// 60 s cache). HONESTY: every glow or slide follows a real change (a new price, a new fill, a new liquidation, a P&L
// that moved), none under prefers-reduced-motion or while the page is hidden; paper only, no order buttons; DeepSeek
// and coin-flip money is never shown here (counts only).
import {h, store, local, motion, bars, features} from "../core/pb.js";
import {topBar} from "./terminal-top.js";
import {watchList, fillsFeed, liqFeed} from "./terminal-feed.js";
import {termChart} from "./terminal-chart.js";
import {coinPositions, pnlPanel} from "./terminal-side.js";
import {bottomTable} from "./terminal-table.js";
import {bookPanel} from "./positions-book.js";
import {panel, duoSwitch, ping, ages} from "./terminal-kit.js";
import {tickStream, bigFeed} from "./terminal-live.js";

export async function mount(el, ctx) {
  ctx.setTitle("터미널");
  const st = {sym: local.get("term-sym", "BTCUSDT"), tf: local.get("term-tf", "15m")};
  if (!bars.SYMS.includes(st.sym)) st.sym = "BTCUSDT";
  if (ctx.params.arg && bars.SYMS.includes(ctx.params.arg)) st.sym = ctx.params.arg;

  const pick = (s) => {
    if (!bars.SYMS.includes(s) || s === st.sym) return;
    st.sym = s; local.set("term-sym", s);
    top.setSym(s); watch.setSym(s); chart.setSym(s); mine.setSym(s); book.setSym(s); liq.setSym(s); table.setSym(s);
  };

  const top = topBar(ctx, st);
  const watch = watchList(ctx, st, pick);
  const fills = fillsFeed(ctx);
  const liq = liqFeed(ctx, st, (fresh) => { for (const r of fresh || []) chart.onLiq(r); });   // new liquidations flash the chart
  const big = bigFeed(ctx);
  const chart = termChart(ctx, st, (tf) => { st.tf = tf; local.set("term-tf", tf); });
  const mine = coinPositions(ctx, st);
  const book = bookPanel(ctx, st.sym, {rows: 5});
  // the book loads only while it is on screen; its first shimmer would stay up while the 호가 switch is off (a shimmer
  // means a request in flight), so it starts empty and fills on its first answer
  book.querySelectorAll(".skel").forEach((x) => x.remove());
  const pnl = pnlPanel(ctx);
  const table = bottomTable(ctx, st, pick);

  const bookP = panel("호가", {sub: "위 20개 기준", cls: "term-book"}, book);
  const left = h("aside", {class: "term-col term-left", "aria-label": "실시간 큰 체결, 시장 강제청산, 우리 봇 체결"}, big.el, liq.el, fills.el);
  const mid = h("div", {class: "term-mid"}, watch.el, chart.el, table.el);
  const right = h("aside", {class: "term-col term-right", "aria-label": "이 코인과 수익"}, mine.el, bookP, pnl.el);
  // this coin's positions and the order book share one place (a small switch in both heads; terminal.css)
  duoSwitch(right, "duo", [{id: "pos", label: "포지션", panel: mine.el}, {id: "book", label: "호가", panel: bookP}], (id) => { if (id === "book") book.load(); });
  const root = h("div", {class: "term"}, top.el, h("div", {class: "term-grid"}, left, mid, right));
  el.append(h("h1", {class: "term-sr"}, "터미널"), root);

  // page hidden: the slow lines and breathing marks stop (CSS reads data-still); reduced motion is handled in CSS
  const still = () => { root.dataset.still = document.hidden ? "1" : ""; };
  still();
  ctx.listen(document, "visibilitychange", still);

  // shared data: one watcher per key, handed to the parts
  ctx.watch("ticker", (tk) => { if (!tk) return; top.onTicker(tk); watch.onTicker(tk); mine.onTicker(); table.onTicker(); chart.onTicker(tk); });
  ctx.watch("board", (b) => { if (!b) return; fills.onBoard(b); mine.onBoard(b); table.onBoard(b); chart.onBoard(b); pnl.onBoard(b); });
  ctx.on("trades", (rows) => { fills.onTrades(rows); table.onTrades(rows); chart.onTrades(rows); });
  const syncLiq = () => left.classList.toggle("has-liq", !!features.liq);
  syncLiq();
  ctx.on("features", () => { syncLiq(); watch.onFeatures(); liq.onFeatures(); });
  // the clock, the funding countdown, the chart's bar countdown and the lists' ages ('6s', '4m'): text only, no request
  ctx.every(1000, () => { top.tick(); chart.tick(); ages(left); }, {now: true});

  // 터미널 살아 있게: the server's real market-trade relay while this screen is on screen and the page visible (each
  // message lights only what it carries: the live dot, that coin's strip button, the selected coin's price and tag)
  const ticks = tickStream(ctx);
  ticks.on((m) => {
    top.onRelay(m);
    for (const ev of Array.isArray(m.ev) ? m.ev : []) {
      if (!ev || typeof ev.s !== "string") continue;
      watch.onTick(ev);
      if (ev.s === st.sym) { top.onTick(ev); chart.onTick(ev); }
    }
    big.onMsg(m);
    // a new big taker trade of this coin flashes the chart once (the first message's rows are the past: no flash)
    if (!m.first && m.big && Array.isArray(m.big.rows)) for (const r of m.big.rows) if (r && r.s === st.sym) chart.onBig(r);
  });
  ticks.start();
  // the bottom table lights its head when real closed trades arrived (its 체결 tab changed)
  ctx.on("trades", (rows) => { if (Array.isArray(rows) && rows.length) ping(table.el); });

  await Promise.all([store.need("board", 60000).catch(() => null), chart.ready, fills.ready]);
  if (!ctx.alive()) return;
  motion.fadeIn(root, 240);
}

export function unmount() {}

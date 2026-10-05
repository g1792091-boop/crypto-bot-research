// #/terminal — 터미널 (wave 2, the PC one-screen view; owners 10/05: the old v3 트레이드 tab's density with the
// reference's "AI" look). One screen, no page scroll on a PC: a top bar (coin, price, 24 h numbers, funding and the
// time to it, session, KST clock, a slow line of the latest real AI meeting conclusions), left (watchlist with
// GH Coin calls while that recorder runs, OUR bots' fills as they happen, market liquidations while that recorder
// runs), centre (the chart: lightweight-charts through core/lwc like 차트, our entries / exits / stops, support /
// resistance, macro releases with a tooltip, the price tag with the bar-close countdown) over the positions table
// (포지션 / 체결 / 손절 주문, long / short / flat bar), right (this coin's positions with live ROE and liquidation price,
// the order book, the chosen group's median return line with daily bars and the profit calendar).
// Data: the same routes and the same cadence as 차트 / 포지션 / 시장 / 흐름 (store ticker 5 s, forming bar 5 s, book
// 3 s, liquidations 10 s, levels 2 min, GH Coin / race / calendar 5 min); nothing new is polled. HONESTY: every glow or
// slide follows a real change (a new price, a new fill, a new liquidation, a P&L that moved), none under
// prefers-reduced-motion or while the page is hidden; paper only, no order buttons.
import {h, store, local, motion, bars, features} from "../core/pb.js";
import {topBar} from "./terminal-top.js";
import {watchList, fillsFeed, liqFeed} from "./terminal-feed.js";
import {termChart} from "./terminal-chart.js";
import {coinPositions, pnlPanel} from "./terminal-side.js";
import {bottomTable} from "./terminal-table.js";
import {bookPanel} from "./positions-book.js";
import {panel, duoSwitch} from "./terminal-kit.js";

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
  const liq = liqFeed(ctx, st);
  const chart = termChart(ctx, st, (tf) => { st.tf = tf; local.set("term-tf", tf); });
  const mine = coinPositions(ctx, st);
  const book = bookPanel(ctx, st.sym, {rows: 5});
  // the book loads only while it is on screen; its first shimmer would stay up while the 호가 switch is off (a shimmer
  // means a request in flight), so it starts empty and fills on its first answer
  book.querySelectorAll(".skel").forEach((x) => x.remove());
  const pnl = pnlPanel(ctx);
  const table = bottomTable(ctx, st, pick);

  const bookP = panel("호가", {sub: "위 20개 기준", cls: "term-book"}, book);
  const left = h("aside", {class: "term-col term-left", "aria-label": "관심 종목과 실시간 체결"}, watch.el, fills.el, liq.el);
  const mid = h("div", {class: "term-mid"}, chart.el, table.el);
  const right = h("aside", {class: "term-col term-right", "aria-label": "이 코인과 손익"}, mine.el, bookP, pnl.el);
  // a window under 940 px tall: this coin's positions and the book share a place, and so do our fills and the
  // market liquidations (a small switch in both heads; terminal.css)
  duoSwitch(right, "duo", [{id: "pos", label: "포지션", panel: mine.el}, {id: "book", label: "호가", panel: bookP}], (id) => { if (id === "book") book.load(); });
  duoSwitch(left, "duo", [{id: "fills", label: "체결", panel: fills.el}, {id: "liq", label: "청산", panel: liq.el}], (id) => { if (id === "liq") liq.load(); });
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
  ctx.every(1000, () => { top.tick(); chart.tick(); }, {now: true});

  await Promise.all([store.need("board", 60000).catch(() => null), chart.ready, fills.ready]);
  if (!ctx.alive()) return;
  motion.fadeIn(root, 240);
}

export function unmount() {}

// 거래 screens (builder B): one coin's head (last price, 24h change, mark, funding and time to it, 24h high / low) and
// its order book (/api/depth, top 20 from the server, polled every 3 s only while the book is on screen). Shared by
// positions (a chosen coin) and chart (the 호가 tab). No Binance WebSocket: prices come through the server.
import {h, ui, fmt, store, serverNow, motion} from "../core/pb.js";
import {fundTone, fundWho} from "../core/fundkit.js";      // one funding colour rule (not a loss colour)

/** "2:13:04" until a timestamp (server clock). */
export function countdown(ts) {
  if (!ts) return "—";
  const left = Math.max(0, Math.floor((ts - serverNow()) / 1000));
  const hh = Math.floor(left / 3600), mm = Math.floor((left % 3600) / 60), ss = left % 60;
  const two = (x) => String(x).padStart(2, "0");
  return `${hh}:${two(mm)}:${two(ss)}`;
}

/** Funding rate as a percent with 4 decimals ("0.0100%"); positive = longs pay. */
export const fundPct = (r) => (r == null ? "—" : fmt.num(Number(r) * 100, 4, true) + "%");

/** The coin head: {el, update(tickerMap), tick()} (tick refreshes the funding countdown every second). */
export function coinHead(sym, o = {}) {
  const px = h("b", {class: "pos-px num"}, "—"), chg = h("span", {class: "num"}, "—");
  const mark = h("b", {class: "num"}, "—"), fund = h("b", {class: "num"}, "—"), fundLeft = h("span", {class: "num muted"}, "");
  // high and low as two unbreakable numbers with a break allowed between them (a 340 px side column is too narrow
  // for "63,710.4 / 61,027.2" on one line)
  const hi = h("span", {class: "num"}, "—"), lo = h("span", {class: "num"}, "");
  const hilo = h("b", null, hi, " / ", lo);
  let T = null;
  const el = h("div", {class: "pos-head"},
    h("div", {class: "pos-head-top"}, h("span", {class: "pos-sym"}, `${fmt.coin(sym)}USDT`), h("span", {class: "muted pos-perp"}, "무기한"),
      h("span", {class: "grow"}), o.chartHref ? h("a", {class: "btn-line", href: o.chartHref}, "이 코인 차트") : null),
    h("div", {class: "pos-head-px"}, px, chg),
    ui.kv([["마크 가격", mark], ["펀딩비 / 남은 시간", h("span", null, fund, " ", fundLeft)], ["24시간 고가 / 저가", hilo]]));
  el.update = (tk) => {
    const t = tk && tk[sym];
    if (!t) return;
    motion.tickPrice(px, t.c ?? t.mark, fmt.price(t.c ?? t.mark), sym);      // glows teal / pink on a real move
    px.className = "pos-px num " + fmt.tone(t.p);
    chg.textContent = t.p == null ? "—" : `24시간 ${fmt.pct(Number(t.p) / 100, 2)}`;
    chg.className = "num " + fmt.tone(t.p);
    motion.tickPrice(mark, t.mark, fmt.price(t.mark), sym);
    fund.textContent = fundPct(t.r);
    fund.className = "num " + fundTone(t.r); fund.title = fundWho(t.r);
    hi.textContent = fmt.price(t.h); lo.textContent = fmt.price(t.l);
    T = t.T || null;
    fundLeft.textContent = T ? countdown(T) : "";
  };
  el.tick = () => { if (T) fundLeft.textContent = countdown(T); };
  return el;
}

/**
 * The order book: bookPanel(ctx, sym, {rows}) -> element with .setSym(sym). Polls /api/depth every 3 s while it is
 * connected to the page (ctx stops the poll when the screen is left). Rows: asks above, bids below, a bar per level
 * by size, the buy / sell share of the top 20 levels.
 */
export function bookPanel(ctx, sym, o = {}) {
  const n = o.rows || 7;
  const list = h("div", {class: "pos-book", role: "table", "aria-label": "호가"});
  const note = h("p", {class: "pos-note"}, "호가 (서버 경유, 3초마다) · 위 20개 호가 기준 매수/매도 비율");
  const el = h("div", {class: "stack tight"}, list, note);
  let cur = sym, busy = false, shown = false;
  const lvl = (x, cls, mx) => h("div", {class: ["pos-bk", cls], role: "row"},
    h("i", {style: {width: Math.min(100, (x[1] / mx) * 100).toFixed(1) + "%"}}),
    h("span", {class: "num"}, fmt.price(x[0])), h("span", {class: "num"}, fmt.num(x[1], x[1] < 10 ? 3 : 1)));
  const render = (d) => {
    const asks = (d.asks || []).slice(0, n).reverse(), bids = (d.bids || []).slice(0, n);
    const mx = Math.max(1e-12, ...asks.map((x) => x[1]), ...bids.map((x) => x[1]));
    const bq = (d.bids || []).reduce((s, x) => s + x[1], 0), aq = (d.asks || []).reduce((s, x) => s + x[1], 0);
    const share = bq + aq > 0 ? bq / (bq + aq) : 0.5;
    const t = (store.get("ticker") || {})[cur];
    list.replaceChildren(
      h("div", {class: "pos-bk hd", role: "row"}, h("span", null, "가격 (USDT)"), h("span", null, `수량 (${fmt.coin(cur)})`)),
      ...asks.map((x) => lvl(x, "a", mx)),
      h("div", {class: ["pos-bk", "mid", t ? fmt.tone(t.p) : ""], role: "row"}, h("span", {class: "num"}, t ? fmt.price(t.c) : "—"),
        h("small", {class: "num muted"}, t && t.mark ? `마크 ${fmt.price(t.mark)}` : "")),
      ...bids.map((x) => lvl(x, "b", mx)),
      h("div", {class: "pos-bkbar"}, h("span", {class: "up num"}, `매수 ${fmt.pct(share, 1, false)}`),
        h("div", null, h("i", {style: {width: (share * 100).toFixed(1) + "%"}})), h("span", {class: "down num"}, `매도 ${fmt.pct(1 - share, 1, false)}`)));
    shown = true;
  };
  const load = async () => {
    if (busy || !cur || !el.isConnected || !el.getClientRects().length) return;      // only while on screen
    busy = true;
    const want = cur;
    try {
      const d = await ctx.api(`/api/depth?symbol=${encodeURIComponent(want)}`);
      if (want === cur && ctx.alive()) render(d);
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (want === cur && !shown) list.replaceChildren(ui.errorBox(e, load));
    } finally {
      busy = false;
      if (want !== cur && ctx.alive()) load();          // the coin changed while this one was in flight
    }
  };
  list.append(...Array.from({length: 2}, () => h("div", {class: "skel"}, h("i"), h("i"), h("i"))));
  ctx.every(3000, load, {now: false});
  el.setSym = (s) => { if (s === cur) return; cur = s; shown = false; list.replaceChildren(h("div", {class: "skel"}, h("i"), h("i"), h("i"))); load(); };
  el.load = load;
  requestAnimationFrame(load);
  return el;
}

// 실거래 › 차트 (#/livebots/chart?sym=&tf=): the open positions of 페이퍼 · 바이비트 · MEXC on the price chart, big. The rule
// bot's terminal chart (terminal-chart.js with a `src`: core/lwc.js, /api/candles 500 bars + the forming bar every 5 s, the
// chart deck of core/chartfx.js with its glow, the Premium / Discount light blinking with the real market trades
// (core/blink.js) and a wash (core/flash.js) on a real big trade, a liquidation, or a live bot that really filled on this
// coin; the same '조명' / '번쩍임' settings as everywhere) with each account's entry line, its stop or lock line, the paper's
// first stop once locked and its next ladder step (순ROE 11 %, then every 3 %), and the marks of the accounts' recent
// trades on that coin. Under the chart the same lines in words, each with its distance from the mark, and the coin's
// recent trades. HONESTY: the lines are the records' prices, the distances are the dashboard's own mark; nothing moves
// without a real change; no order buttons.
import {h, put, ui, fmt, store, local, motion, bars} from "../core/pb.js";
import {watchList} from "./terminal-feed.js";
import {termChart} from "./terminal-chart.js";
import {tickStream} from "./terminal-live.js";
import {coinMarks} from "./livebots-parts.js";
import {liveLines, acctKo, acctTag, sourceState} from "./livebots-kit.js";
import {posKeys, roeAt, netRoe, distTo} from "./livebots-calc.js";

const TFS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

/** chartView(ctx, hub) -> {el, set(d, state)} */
export function chartView(ctx, hub) {
  const q = ctx.params.query || {};
  const st = {sym: local.get("lb-sym", "BTCUSDT"), tf: local.get("lb-ctf", "15m"), d: null, state: "loading"};
  if (q.sym && bars.SYMS.includes(q.sym)) st.sym = q.sym;
  if (q.tf && TFS.includes(q.tf)) st.tf = q.tf;
  if (!bars.SYMS.includes(st.sym)) st.sym = "BTCUSDT";
  if (!TFS.includes(st.tf)) st.tf = "15m";
  const pick = (s) => {
    if (!bars.SYMS.includes(s) || s === st.sym) return;
    st.sym = s; local.set("lb-sym", s);
    watch.setSym(s); chart.setSym(s); drawCards(true);
  };
  const marks = coinMarks();
  const watch = watchList(ctx, st, pick, {marks});
  const chart = termChart(ctx, st, (tf) => { st.tf = tf; local.set("lb-ctf", tf); }, {
    key: "live", label: "실거래 차트",
    keyTitle: "페이퍼(P) · 바이비트(B) · MEXC(M)의 진입선, 손절·잠금선, 페이퍼의 첫 손절과 다음 잠금 자리 (순ROE 11%, 그 뒤 3%마다) · 왼쪽 이름표를 누르면 그 선만 숨김",
    more: (sym, tf) => ctx.href("chart", sym, {tf}),
    lines: (sym, mark) => liveLines(st.d ? st.d.accts : [], sym, mark),
    posKeys: (sym) => posKeys(st.d ? st.d.accts : [], sym),
    trades: (sym) => (st.d ? (st.d.marks || []).filter((m) => m.symbol === sym) : []),
  });
  chart.el.querySelector(".term-more").textContent = "시장 차트 →";
  const cards = h("div", {class: "lb-lines"});
  const recent = h("div", {class: "lb-recent"});
  const el = h("div", {class: "term lb-chartv"}, watch.el, h("div", {class: "lb-cbig"}, chart.el),
    ui.card({title: "선 읽기", sub: "차트의 선을 말로 · 거리는 지금 마크 가격에서", cls: "lb-linecard"}, cards),
    ui.card({title: "이 코인 최근 거래", sub: "세 계좌의 닫힌 거래 (차트의 표시)", cls: "lb-recentcard"}, recent),
    h("div", {class: "lb-foot"}, ui.assumeLive("바이비트 · MEXC"), ui.assumeLine(["closed", "open"], "페이퍼(P)")));

  const row = (k, v, extra) => h("div", {class: "lb-lrow"}, h("span", {class: "lb-lk"}, k), h("b", {class: "num"}, v), extra ? h("span", {class: "lb-lx muted num"}, extra) : null);
  const dist = (mk, price) => { const x = distTo(mk, price); return x == null ? "마크 없음" : `지금에서 ${fmt.pct(x, 2, false)}`; };
  let sigCards = null;
  function drawCards(force) {
    const d = st.d;
    if (!d) { put(cards, st.state === "failed" ? ui.errorBox(new Error("불러오지 못함"), () => hub.retry()) : motion.shimmer(3)); put(recent, motion.shimmer(2)); return; }
    const mk = store.mark(st.sym);
    const sig = JSON.stringify([st.sym, d.accts.map((a) => [a.id, a.state, a.position]), mk && Math.round(mk * 100)]);
    if (!force && sig === sigCards) return;
    sigCards = sig;
    const blocks = d.accts.map((a) => {
      if (a.state !== "ok") return h("div", {class: "lb-lblock"}, h("div", {class: "lb-lhead2"}, acctTag(a.id)), sourceState(a, acctKo(a.id)));
      const p = a.position;
      if (!p || p.symbol !== st.sym) {
        return h("div", {class: "lb-lblock flat"}, h("div", {class: "lb-lhead2"}, acctTag(a.id)),
          h("p", {class: "lb-flat"}, p ? `${fmt.coin(st.sym)} 포지션 없음 · 지금 ${fmt.coin(p.symbol)} ${fmt.sideKo(p.side)} 보유` : `${fmt.coin(st.sym)} 포지션 없음`));
      }
      const roe = roeAt(p, mk), net = a.kind === "paper" ? netRoe(p, mk) : null, nx = p.next_lock;
      return h("div", {class: "lb-lblock"},
        h("div", {class: "lb-lhead2"}, acctTag(a.id), ui.sideTag(p.side), h("span", {class: "muted num"}, fmt.lev(p.leverage)),
          roe != null ? h("b", {class: ["num", fmt.tone(roe)]}, `ROE ${fmt.pct(roe, 1)}`) : null,
          net != null ? h("span", {class: ["num", "muted"]}, `순ROE ${fmt.pct(net, 1)}`) : null,
          p.status === "entering" ? ui.pill("진입 확인 중", "warn") : null),
        row("진입", fmt.price(p.entry), p.entry_time ? fmt.kst(p.entry_time) : null),
        p.locked && p.stop_initial ? row("첫 손절", fmt.price(p.stop_initial), "잠금 전의 손절") : null,
        row(p.locked ? "지금 잠금선" : "지금 손절선", fmt.price(p.stop), dist(mk, p.stop) + (p.lock_roe != null ? ` · 잠금 순ROE ${fmt.pct(p.lock_roe, 0, false)}` : "")),
        nx && nx.price ? row("다음 잠금", fmt.price(nx.price), `순ROE ${fmt.pct(nx.at, 0, false)}에서 ${fmt.pct(nx.lock, 0, false)} 잠금 · ${dist(mk, nx.price)}${nx.from === "paper" ? " · 페이퍼 기준" : ""}`) : null,
        p.liq ? row("청산가", fmt.price(p.liq), dist(mk, p.liq)) : a.kind === "live" ? row("청산가", "—", "실행기 기록에 없음 (거래소 앱에서)") : null,
        a.kind === "live" ? row("거래소 손절 주문", p.stop_order ? `#${String(p.stop_order).slice(-8)}` : "번호 기록 없음") : null);
    });
    put(cards, blocks);
    const ms = (d.marks || []).filter((m) => m.symbol === st.sym).slice(0, 10);
    put(recent, ms.length ? h("div", {class: "lb-rlist", role: "list"}, ms.map((m) => h("div", {class: "lb-rrow", role: "listitem"},
      h("span", {class: "num muted"}, fmt.kst(m.exit_time)), acctTag(m.acct), ui.sideTag(m.side),
      h("b", {class: ["num", fmt.tone(m.pnl)]}, m.pnl == null ? "—" : fmt.money(m.pnl, true)))))
      : ui.empty(`${fmt.coin(st.sym)}의 닫힌 거래가 아직 없어요`));
  }

  ctx.watch("ticker", (tk) => { if (!tk) return; watch.onTicker(tk); chart.onTicker(tk); drawCards(false); });
  ctx.every(1000, () => chart.tick(), {now: true});
  const ticks = tickStream(ctx);
  ticks.on((m) => {
    for (const ev of Array.isArray(m.ev) ? m.ev : []) {
      if (!ev || typeof ev.s !== "string") continue;
      watch.onTick(ev);
      if (ev.s === st.sym) chart.onTick(ev);
    }
    if (!m.first && m.big && Array.isArray(m.big.rows)) for (const r of m.big.rows) if (r && r.s === st.sym) chart.onBig(r);
  });
  ticks.start();
  drawCards(true);
  return {
    el,
    set(d, state) {
      st.state = state;
      if (d) st.d = d;
      watch.onBoard(st.d, state === "failed" && !st.d);
      chart.refresh();
      drawCards(false);
    },
  };
}

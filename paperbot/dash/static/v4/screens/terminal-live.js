// 터미널 살아 있게 (owners 10/06 03:48: "빛나거나 막 움직이는 게 안 보인다, 화면이 부족하다"). The terminal reads the
// server's market-trade relay (/api/v4/ticks, dash/more/ticks.py: ONE Binance aggTrade socket on the server shared by
// every page) while it is on screen and the page is visible, and every motion here answers one real message of it:
//   - a relay event (a real burst of market trades of one coin, at most ~2 a second for all coins together) lights
//     that coin's watchlist row, the top price and the chart's price tag (the selected coin), and the live dot;
//   - 실시간 큰 체결: real large market orders of the whole Binance market (NOT our bots), newest on top, with the
//     5-minute taker buy / sell notional of those orders and a 고래 badge from 4 times the coin's threshold.
// HONESTY: no message, no motion (no timer animates anything); the feed is labelled as the whole market's trades, not
// ours; nothing under prefers-reduced-motion; the page's one relay connection (core/ticks.js) is closed while the page is
// hidden, and this screen's listener leaves when the screen is left.
import {h, put, ui, fmt, motion, listenTicks, ticksState} from "../core/pb.js";
import {panel, ratioBar, ping, ageCell, MARKET_LABEL} from "./terminal-kit.js";

export const BIG_LABEL = "바이낸스 시장 전체 체결 (우리 봇 아님)";
export const BIG_SHOW = 20;                         // rows on screen (the relay keeps 40)
const BIG_MEM = 40;
const SIDE_KO = {buy: "매수", sell: "매도"};
const live = () => motion.visible() && !motion.reduced();
const two = (x) => String(x).padStart(2, "0");
/** Korea time hh:mm:ss of a trade (ms). */
export const hms = (ms) => { const d = new Date(Number(ms) + 9 * 3.6e6); return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}:${two(d.getUTCSeconds())}`; };
/** $412K / $1.25M */
export const usdK = (x) => "$" + (x >= 1e6 ? `${fmt.num(x / 1e6, 2)}M` : `${fmt.num(x / 1e3, 0)}K`);

/**
 * A one-shot light on a real tick: data-hit="up" | "down" restarts the element's CSS animation (terminal.css), which
 * removes itself at its end. Skipped under reduced motion and on a hidden page. Returns the element.
 */
export function hit(el, tone) {
  if (!el || !tone || !live()) return el;
  el.removeAttribute("data-hit");
  void el.offsetWidth;                              // restart the animation (a second tick while the first one glows)
  el.dataset.hit = tone;
  if (!el._hitEnd) {
    el._hitEnd = (e) => { if (e.target === el) el.removeAttribute("data-hit"); };
    el.addEventListener("animationend", el._hitEnd);
  }
  return el;
}

/**
 * tickStream(ctx) -> {on(fn), start(), state()}: the relay's server-sent events while the screen is mounted and the
 * page is visible, through the page's ONE relay connection (core/ticks.js, shared with the sound and the chart light:
 * closed while the page is hidden, opened again when shown; this screen's listener leaves when the screen is left).
 * fn(msg) gets every message {state, ev, big?, first}; a dropped connection is told as {state: "down", ev: []}; a
 * refused one is asked again after 30 s, then a growing wait up to 5 minutes.
 */
export function tickStream(ctx) {
  const subs = [];
  let off = null;
  const tell = (m) => { for (const fn of subs) { try { fn(m); } catch (e) { /* one part failing never stops the others */ } } };
  function open() {
    if (off || !ctx.alive()) return;
    off = listenTicks(tell);
  }
  function close() { if (off) { const f = off; off = null; f(); } }
  ctx.track(close);
  return {on(fn) { subs.push(fn); }, start: open, state: () => (off ? ticksState() : "off")};
}

/** bigFeed(ctx) -> {el, onMsg(msg), rows(sym)}: 실시간 큰 체결 (the whole market's large orders, not ours). */
export function bigFeed(ctx) {
  const st = {rows: [], keys: new Set(), nodes: new Map(), min: null, wx: 4, state: "off"};
  const list = h("div", {class: "term-feed term-big", role: "list", "aria-live": "off"});
  const stateEl = h("span", {class: "term-bst", "data-s": "off"}, h("i", {"aria-hidden": "true"}), h("span", null, "연결 전"));
  const ratio = ratioBar([{key: "buy", label: "매수", tone: "up"}, {key: "sell", label: "매도", tone: "down"}], {label: "최근 5분 큰 체결 매수·매도 금액"});
  const ratioK = h("span", {class: "term-rbk"}, "최근 5분");
  const minNote = h("span", {class: "term-bmin"});
  const label = h("p", {class: "note term-blab"}, h("b", null, BIG_LABEL), " ", minNote);
  const el = panel("실시간 큰 체결", {cls: "term-bigp", sub: MARKET_LABEL, scroll: true, acts: [stateEl]}, list);
  el.append(h("div", {class: "term-pf"}, h("div", {class: "term-rbrow"}, ratioK, ratio), label));
  put(list, ui.empty("시장 체결을 기다리는 중"));

  const keyOf = (r) => `${r.t}:${r.s}:${r.side}:${r.usd}`;
  function paintMin() {
    const m = st.min || {};
    const f = (s) => (m[s] ? usdK(m[s]) : "—");
    minNote.textContent = `· 주문 한 번에 BTC ${f("BTCUSDT")} · ETH ${f("ETHUSDT")} · 나머지 ${f("SOLUSDT")} 이상 · 고래 = ${fmt.int(st.wx)}배 이상`;
    label.title = BIG_LABEL + " " + minNote.textContent;      // (a short footer hides the thresholds: the tooltip keeps them)
  }
  paintMin();
  // one dense line per order (term v2): ▲ / ▼ coin · price · 고래 · $ · age, the row tinted by its side
  function rowOf(r) {
    const tone = r.side === "buy" ? "up" : "down";
    return h("div", {class: ["term-fr", "big", r.side, r.w ? "whale" : ""], role: "listitem",
      title: `${fmt.coin(r.s)} ${SIDE_KO[r.side]} ${usdK(r.usd)} · ${hms(r.t)} · 기준의 ${fmt.num(r.x, 1)}배 · 체결 ${fmt.int(r.n)}건 묶음 (${BIG_LABEL})`},
    h("b", {class: ["term-bc", tone]}, h("i", {class: "term-bar", "aria-hidden": "true"}, r.side === "buy" ? "▲" : "▼"), fmt.coin(r.s),
      h("span", {class: "term-sr"}, ` ${SIDE_KO[r.side]}`)),
    h("span", {class: ["num", "term-lp", tone]}, fmt.price(r.p)),
    r.w ? h("span", {class: "term-whale"}, "고래") : h("span", {class: "term-wsp", "aria-hidden": "true"}),
    h("b", {class: ["num", "term-bu"]}, usdK(r.usd)),
    ageCell(r.t));
  }
  function render(fresh) {
    const show = st.rows.slice(0, BIG_SHOW);
    if (!show.length) { put(list, ui.empty(st.state === "live" ? "아직 큰 체결이 없습니다" : st.state === "down" ? "시장 체결 연결이 끊겼습니다 · 다시 연결 중" : "시장 체결을 기다리는 중")); return; }
    const nodes = show.map((r) => {
      const k = keyOf(r);
      let n = st.nodes.get(k);
      if (!n) {
        n = rowOf(r);
        st.nodes.set(k, n);
        if (fresh.has(k) && live()) { motion.fillIn(n, r.side === "buy" ? "up" : "down"); if (r.w) motion.ring(n, r.side === "buy" ? "up" : "down"); }
      }
      return n;
    });
    const keep = new Set(show.map(keyOf));
    for (const k of st.nodes.keys()) if (!keep.has(k)) st.nodes.delete(k);
    list.replaceChildren(...nodes);
  }
  function paintState(s) {
    st.state = s;
    stateEl.dataset.s = s;
    stateEl.lastChild.textContent = s === "live" ? "실시간" : s === "connecting" ? "연결 중" : s === "down" ? "끊김" : "연결 전";
    stateEl.title = `시장 체결 연결: ${stateEl.lastChild.textContent}`;
  }
  return {
    el,
    onMsg(m) {
      const was = st.state;
      paintState(m.state);
      const b = m.big;
      if (b && typeof b === "object") {
        if (b.min) { st.min = b.min; st.wx = Number(b.whale_x) || 4; paintMin(); }
        const fresh = new Set();
        for (const r of Array.isArray(b.rows) ? b.rows : []) {
          if (!r || !r.s || (r.side !== "buy" && r.side !== "sell")) continue;
          const k = keyOf(r);
          if (st.keys.has(k)) continue;
          st.keys.add(k);
          if (!m.first) fresh.add(k);              // the first message's list is the past: drawn without motion
          st.rows.push(r);
        }
        st.rows.sort((x, y) => y.t - x.t);
        if (st.rows.length > BIG_MEM) { for (const r of st.rows.splice(BIG_MEM)) st.keys.delete(keyOf(r)); }
        const span = Number(b.span) || 0;
        if (m.state === "live" && span > 0) {
          ratioK.textContent = span >= 290 ? "최근 5분" : `최근 ${fmt.int(Math.max(1, Math.round(span / 60)))}분`;
          ratio.set({buy: Number(b.buy) || 0, sell: Number(b.sell) || 0}, (n, sh) => `${fmt.pct(sh, 0, false)} · $${fmt.compact(n)}`);
        }
        if (fresh.size || m.first || was !== m.state) { render(fresh); if (fresh.size) ping(el); }   // (a new state: the empty line says it)
      } else if (was !== m.state) render(new Set());
      if (m.state !== "live") { ratioK.textContent = "최근 5분"; ratio.set({}); }
    },
    /** The kept large orders of one coin, newest first (for 이 코인 포지션 when it has none). */
    rows(sym) { return st.rows.filter((r) => r.s === sym); },
    rowOf,
  };
}

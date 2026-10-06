// 우리 손절·청산 지도 (chart-plus, addition 11): a thin strip beside the price axis of the coin on screen, from OUR open
// paper positions: where their stop prices (yellow) and liquidation prices (pink) are, a bar and a count at each price.
// Hover (or tap) a price: "이 가격이면: 손절 n개 · 청산 m개 · 예상 손익 …" computed from those positions (chart-plus-calc
// whatIf: marks only, before the exit fee and slippage, the arithmetic of what is open, not a forecast). DeepSeek and
// the coin flips are COUNTED in every number but their money is never added (CONTRACT D10 / D11: counted, not summed).
// It reads the shared board (ctx.watch("board"), the same /api/board every screen shares) and the mark (store.mark).
import {h, fmt, store} from "../core/pb.js";
import {normPos, countOnly} from "./positions-kit.js";
import {whatIf, stopLevels} from "./chart-plus-calc.js";
import {koUsdt, WORDS, tipBox, palette} from "./chart-plus-kit.js";

/** stopMap({ctx, chart, series, wrap, deck, strip, sym, report}) -> {setOn(on), onData(), paint(), view()}
 *  report(view): {kind: "off" | "waiting" | "none" | "ready", n, stops, liqs, countOnly}  for the note under the chart */
export function stopMap(o) {
  const {ctx, chart, series, wrap, strip} = o;
  const cv = h("canvas", {class: "cfxp-cv", "aria-hidden": "true"});
  strip.append(cv);
  strip.title = "우리 모의 계좌의 이 코인 열린 포지션: 손절가(노랑)와 청산가(분홍). 가격 막대에 마우스를 올리면 '이 가격이면'.";
  const tip = tipBox(wrap);
  let on = false, board = null, items = [], levels = [], aim = null;

  function collect() {
    const sym = o.sym();
    items = [];
    for (const a of (board && board.accounts) || []) {
      if (!a || !a.position || a.position.symbol !== sym) continue;
      const p = normPos(a.position);
      if (!p || !(p.entry > 0)) continue;
      items.push({id: a.account_id, side: p.side, entry: p.entry, qty: p.qty || 0, margin: p.margin || 0, stop: p.stop, liq: p.liq,
        lock: p.lock_roe != null && !fmt.ownExits(a), money: !countOnly(a, "")});
    }
    levels = stopLevels(items);
  }
  const mark = () => store.mark(o.sym());
  function view() {
    if (!on) return {kind: "off"};
    if (!board) return {kind: "waiting"};
    if (!items.length) return {kind: "none"};
    return {kind: "ready", n: items.length, stops: levels.filter((l) => l.kind === "stop").reduce((s, l) => s + l.n, 0),
      liqs: levels.filter((l) => l.kind === "liq").reduce((s, l) => s + l.n, 0), countOnly: items.filter((x) => !x.money).length};
  }
  const report = () => { if (o.report) o.report(view()); };

  // ---------------------------------------------------------------- the strip
  let raf = 0;
  const paintSoon = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; paint(); }); };
  ctx.track(() => { if (raf) cancelAnimationFrame(raf); });
  series.attachPrimitive({paneViews: () => [], updateAllViews() { if (on) paintSoon(); }});
  function paint() {
    const W = strip.clientWidth, H = strip.clientHeight;
    if (!W || !H) return;
    const dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.width = W + "px"; cv.style.height = H + "px";
    }
    const c = cv.getContext("2d");
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, W, H);
    if (!on) return;
    const p = palette(), lh = p.fs + 2;
    c.font = `600 ${p.fs}px ${p.font}`; c.textBaseline = "top"; c.textAlign = "left";
    const stack = W < c.measureText("우리 계좌").width + 8, headH = (stack ? 3 : 2) * lh + 4;       // a narrow strip stacks its header
    const m = mark(), my = m ? series.priceToCoordinate(m) : null;
    if (my != null && my >= 0 && my <= H) { c.globalAlpha = 0.5; c.fillStyle = p.ink2; c.fillRect(0, Math.round(my), W, 1); c.globalAlpha = 1; }
    if (!items.length) {
      c.fillStyle = p.muted; c.textAlign = "center"; c.textBaseline = "middle";
      const msg = board ? ["열린", "포지션", "없음"] : ["불러오는", "중"];
      msg.forEach((t, i) => c.fillText(t, W / 2, H / 2 + (i - (msg.length - 1) / 2) * (p.fs + 3)));
    } else {
      c.textAlign = "left"; c.textBaseline = "middle";
      for (const L of levels) {
        const y = series.priceToCoordinate(L.price);
        if (y == null || y < 0 || y > H) continue;
        const w = Math.min(W - 26, 8 + 7 * (L.n - 1)), color = L.kind === "stop" ? p.warn : p.down;
        c.globalAlpha = 0.9; c.fillStyle = color; c.fillRect(3, Math.round(y) - 1, w, 3);
        if (L.n > 1) { c.globalAlpha = 1; c.fillText(`×${L.n}`, 3 + w + 3, Math.round(y)); }
      }
      c.globalAlpha = 1;
      if (aim != null) {                         // the price under the finger / mouse
        c.fillStyle = p.ink; c.globalAlpha = 0.7; c.fillRect(0, Math.round(aim), W, 1); c.globalAlpha = 1;
      }
    }
    c.globalAlpha = 0.9; c.fillStyle = p.surface; c.fillRect(0, 0, W, headH);            // the header sits on a plate over the marks
    c.globalAlpha = 1; c.textBaseline = "top"; c.textAlign = "left";
    c.fillStyle = p.muted; c.fillText(stack ? "우리" : "우리 계좌", 4, 3);
    c.fillStyle = p.warn; c.fillText("손절", 4, 3 + lh);
    c.fillStyle = p.down; c.fillText("청산", stack ? 4 : 4 + c.measureText("손절 ").width, 3 + (stack ? 2 : 1) * lh);
  }

  // ---------------------------------------------------------------- "이 가격이면"
  function say(P, clientX, clientY) {
    const m = mark();
    const wr = wrap.getBoundingClientRect(), x = clientX - wr.left, y = clientY - wr.top;
    if (!items.length) { tip.show([h("b", null, "이 코인의 열린 포지션이 없습니다"), h("small", {class: "muted"}, "우리 모의 계좌 기준")], x, y, strip.parentElement.offsetLeft); return; }
    if (!m) { tip.show([h("b", null, "지금 가격을 못 불러와 계산하지 못했습니다")], x, y, strip.parentElement.offsetLeft); return; }
    const r = whatIf(items, m, P);
    const head = h("b", null, `이 가격이면 · ${fmt.price(P)} (지금보다 ${fmt.pct(P / m - 1, 2)})`);
    const hit = [`손절 ${fmt.int(r.stops)}개`, `청산 ${fmt.int(r.liqs)}개`].join(" · ") + (r.locks ? ` (손절 중 잠금선 ${fmt.int(r.locks)}개)` : "");
    const lines = [head, h("span", null, hit)];
    if (r.nMoney) lines.push(h("span", {class: ["num", fmt.tone(r.pnl)]}, `예상 손익 ${fmt.usdt(r.pnl, true)}`));
    else lines.push(h("span", {class: "muted"}, "예상 손익: 금액을 보이는 계좌가 없습니다"));
    if (r.countOnly) lines.push(h("small", {class: "muted"}, WORDS.countOnly(r.countOnly)));
    lines.push(h("small", {class: "muted"}, `이 코인 열린 포지션 ${fmt.int(r.n)}개 · ${WORDS.stopsMath}`));
    tip.show(lines, x, y, strip.parentElement.offsetLeft);
  }
  function aimAt(e) {
    const r = strip.getBoundingClientRect(), y = e.clientY - r.top;
    const P = series.coordinateToPrice(y);
    if (P == null || !(P > 0)) { clearAim(); return; }
    aim = y; paintSoon();
    say(P, e.clientX, e.clientY);
    // the chart's own crosshair follows the price too, so the axis shows it
    const d = o.deck.data();
    try { if (d.length) chart.setCrosshairPosition(P, d[d.length - 1].time, series); } catch (x) { /* an older build: no crosshair */ }
  }
  function clearAim() {
    aim = null; tip.hide(); paintSoon();
    try { chart.clearCrosshairPosition(); } catch (x) { /* ok */ }
  }
  strip.addEventListener("pointermove", aimAt);
  strip.addEventListener("pointerdown", aimAt);
  strip.addEventListener("pointerleave", clearAim);
  strip.style.touchAction = "none";
  if (ctx.listen) ctx.listen(document, "pointerdown", (e) => { if (aim != null && !strip.contains(e.target)) clearAim(); });          // a tap elsewhere puts the tip away

  ctx.watch("board", (b) => { if (b) { board = b; collect(); paintSoon(); report(); } });
  ctx.watch("ticker", () => { if (on) paintSoon(); });
  return {
    tip,
    setOn(v) { on = !!v; if (!on) { tip.hide(); aim = null; } collect(); paint(); report(); },
    onData(how) { if (how === "set") { collect(); aim = null; tip.hide(); paintSoon(); report(); } },
    paint, view,
  };
}

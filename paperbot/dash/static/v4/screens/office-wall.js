// 회의실 상황판 (fill-people): a pixel wall screen in the wood next to the 대표실. Real numbers only:
//   - the 7 coins' prices from the ticker (/api/ticker, every 5 s; a price flashes only when it really changed)
//   - today's closed trades and wins per group (since 00:00 KST, /api/v4/people/today): 기존 36 / 5분봉 / 추가 with
//     their P&L; DeepSeek and the coin flips COUNTED ONLY (D10/D11)
//   - open positions now (/api/board): money groups by number, DeepSeek / coin flips as counts
//   - the next fixed meeting's countdown (/api/office schedule.next.at_ms: a real scheduled time, nothing invented)
//   - today's loss cards (the code writes one at every losing close of the 36 and the 5-minute strategy)
import {h, put, ui, fmt, store} from "../core/pb.js";
import {triggerKo} from "./rooms-kit.js";

const GROUPS = [["core", "기존 36", true], ["m5", "5분봉", true], ["extra", "추가", true], ["ds", "딥시크", false], ["coin", "동전 봇", false]];

/** "2:41:07" / "41:07" until ts (null when unknown or past). */
export function countdown(ts, now = Date.now()) {
  if (!ts) return null;
  let s = Math.floor((ts - now) / 1000);
  if (s < 0) return null;
  const hh = Math.floor(s / 3600); s -= hh * 3600;
  const mm = Math.floor(s / 60); const ss = s - mm * 60;
  const p = (x) => String(x).padStart(2, "0");
  return hh ? `${hh}:${p(mm)}:${p(ss)}` : `${p(mm)}:${p(ss)}`;
}

/** Open positions per group from the board: {core: n, ...}. */
export function openByGroup(board) {
  const out = {};
  for (const a of (board && board.accounts) || []) if (a.position) { const g = fmt.groupOf(a); out[g] = (out[g] || 0) + 1; }
  return out;
}

export function makeWall(ctx) {
  const prices = new Map();
  const priceBox = h("div", {class: "ow-prices", role: "list", "aria-label": "코인 가격"});
  const cdEl = h("b", {class: "ow-cd num"}, "—");
  const cdWhat = h("span", {class: "ow-cdw"});
  const today = h("div", {class: "ow-today"});
  const openEl = h("div", {class: "ow-open"});
  const cards = h("b", {class: "num"}, "—");
  const stamp = h("span", {class: "ow-stamp"});
  const el = h("section", {class: "of-room ow-wall", "aria-label": "상황판"},
    h("div", {class: "of-room-h"}, h("span", {class: "plate"}, "상황판"), h("span", {class: "grow"}), stamp),
    h("div", {class: "ow-screen"},
      priceBox,
      h("div", {class: "ow-row ow-next"}, h("span", {class: "ow-k"}, "다음 회의까지"), cdEl, cdWhat),
      h("div", {class: "ow-row"}, h("span", {class: "ow-k"}, "오늘 닫힌 거래 (한국 0시부터)"), today),
      h("div", {class: "ow-row ow-two"},
        h("div", null, h("span", {class: "ow-k"}, "지금 열린 포지션"), openEl),
        h("div", null, h("span", {class: "ow-k"}, "오늘 손실 카드"), h("div", {class: "ow-big"}, cards, h("small", null, "장")),
          h("span", {class: "ow-s"}, "지는 거래마다 코드가 씀 (기존 36·5분봉)")))),
    h("p", {class: "ow-foot"}, "모두 실제 기록 · 딥시크·동전 봇은 개수만"));

  let next = null;
  function tick() {
    const t = countdown(next && next.at_ms);
    cdEl.textContent = t || "—";
  }
  ctx.every(1000, tick);

  function paintPrices() {
    const t = store.get("ticker");
    if (!t) { if (!priceBox.children.length) put(priceBox, h("span", {class: "ow-s"}, "시세 불러오는 중")); return; }
    for (const sym of Object.keys(t)) {
      const v = t[sym] && (t[sym].mark ?? t[sym].c);
      if (v == null) continue;
      let p = prices.get(sym);
      if (!p) {
        const num = ui.liveNum(null, {format: (x) => fmt.price(x), glow: true, cls: "ow-px"});
        const chg = h("span", {class: "ow-chg"});
        p = {num, chg, row: h("div", {class: "ow-coin", role: "listitem"}, h("span", {class: "ow-sym"}, fmt.coin(sym)), num, chg)};
        prices.set(sym, p);
        if (!prices.size || priceBox.querySelector(".ow-s")) put(priceBox);
        priceBox.append(p.row);
      }
      p.num.update(Number(v));
      const c = Number(t[sym].p);
      p.chg.textContent = Number.isFinite(c) ? `${c > 0 ? "+" : ""}${fmt.num(c, 1)}%` : "";
      p.chg.className = ["ow-chg", c > 0 ? "up" : c < 0 ? "down" : ""].join(" ");
    }
  }

  function paintToday(d) {
    if (!d || d.error) { put(today, h("span", {class: "ow-s"}, d && d.error ? "기록 없음" : "불러오는 중")); return; }
    const g = d.groups || {};
    put(today, ...GROUPS.filter(([id]) => g[id] || id === "core").map(([id, ko, money]) => {
      const x = g[id] || {n: 0, wins: 0};
      return h("div", {class: "ow-g"}, h("span", {class: "ow-gn"}, ko),
        h("b", {class: "num"}, `${fmt.int(x.n)}건`),
        h("span", {class: "ow-s"}, x.n ? `${fmt.int(x.wins)}승 ${fmt.int(x.n - x.wins)}패` : "아직 없음"),
        money && x.n && x.pnl != null ? h("span", {class: ["num", fmt.tone(x.pnl)]}, fmt.usdt(x.pnl, true)) : h("span", {class: "ow-s"}, money ? "" : "개수만"));
    }));
    cards.textContent = fmt.int(d.loss_cards || 0);
    stamp.textContent = d.computed_at ? `${fmt.hm(d.computed_at)} 기준` : "";
  }

  function paintOpen(b) {
    const o = openByGroup(b);
    const money = (o.core || 0) + (o.m5 || 0) + (o.extra || 0);
    put(openEl, h("div", {class: "ow-big"}, h("b", {class: "num"}, fmt.int(money)), h("small", null, "개")),
      h("span", {class: "ow-s"}, `기존 36 ${fmt.int(o.core || 0)} · 5분봉 ${fmt.int(o.m5 || 0)} · 추가 ${fmt.int(o.extra || 0)}`),
      h("span", {class: "ow-s"}, `딥시크 ${fmt.int(o.ds || 0)} · 동전 봇 ${fmt.int(o.coin || 0)} (개수만)`));
  }

  async function loadToday() {
    try { const d = await ctx.api("/api/v4/people/today"); if (ctx.alive()) paintToday(d); }
    catch (e) { if (ctx.alive() && !(e && e.name === "AbortError")) paintToday({error: "불러오지 못함"}); }
  }
  ctx.watch("ticker", paintPrices);
  ctx.watch("board", (b) => { if (b) paintOpen(b); });
  ctx.every(60000, loadToday);
  ctx.on("trades", () => ctx.timeout(loadToday, 2000));
  paintToday(null);

  return {
    el,
    /** o: /api/office (its schedule.next is the countdown's target). */
    update(o) {
      next = o && o.schedule && o.schedule.next;
      cdWhat.textContent = next ? `${next.tomorrow ? "내일 " : ""}${next.hhmm} ${triggerKo(next)}` : "정해진 시각의 회의 없음";
      tick();
    },
  };
}

// #/market 시장 (CONTRACT 9.1, 9.8): the whole market of each coin (Binance, not our bots), read by the dashboard
// server and cached: price and 24 h change (/api/live, every 10 s), funding of the last three 8-hour rounds and the
// time to the next, open interest now and its 24 h change, and the share of accounts holding longs vs shorts over the
// last 24 hours (/api/market, every 60 s). A plain sentence for every column.
// Round 5 stage 2B (the rule bot's v4 시장 look, market.css / market-live.js): a "코인 온도판" tile per coin (the 24 h
// change, the price that glows once when it really moves, the 24 h low ↔ high bar with the price on it, funding, the
// next funding, open interest, the long / short ratio), built once and updated in place; then the derivatives board
// (one row per coin with its small lines, the v4 mk-fr rows: a table on a PC, labelled cells on a phone); the words
// for every column behind 더 보기.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {COINS} from "../labels.js";
import * as K from "../live-kit.js";

const EXPLAIN = [
  ["가격 · 24시간", "지금 가격과 24시간 전보다 몇 % 올랐나(내렸나). 막대는 24시간 동안의 가장 낮은 값 ↔ 가장 높은 값, 점이 지금 가격."],
  ["펀딩", "8시간마다 롱과 숏이 서로 주고받는 돈의 비율. +면 롱이 숏에게 냅니다. 보통은 +0.0100%이고, 0.05%를 넘으면 한쪽으로 많이 쏠렸다는 뜻이라 주황색으로 보입니다. 작은 그래프는 지난 세 번."],
  ["다음 펀딩까지", "다음에 펀딩을 주고받을 때까지 남은 시간 (한국 시간 01시 · 09시 · 17시)."],
  ["미결제약정", "아직 닫히지 않은 계약 전체의 크기(달러). 늘면 새 돈이 들어오는 중, 줄면 포지션을 정리하는 중. 작은 그래프는 지난 24시간(1시간마다)."],
  ["롱/숏 계정 비율", "바이낸스 계정 가운데 롱을 든 계정 수 ÷ 숏을 든 계정 수. 1보다 크면 롱 계정이 더 많습니다 (돈의 크기가 아니라 계정 수). 괄호 안은 롱 계정의 비율, 작은 그래프는 지난 24시간."],
];
const FUND_HOT = 0.0005;

export async function mount(el, ctx) {
  await K.needCss();
  ctx.setTitle("시장");
  const say = h("div");
  const tilesBox = h("div", {class: "s2-mktemp"});
  const boardBox = h("div");
  const liveLine = h("p", {class: "note"}), stamp = h("p", {class: "note"});
  el.append(ui.screenHead("시장", "코인마다 시장 전체의 숫자 (우리 봇이 아니라 바이낸스 전체)"),
    ui.card({plate: "코인 7개", sub: "가격 10초마다 · 나머지 1분마다 · 누르면 터미널", cls: "s2-mkcard"}, say, tilesBox, liveLine),
    ui.card({plate: "펀딩 · 미결제약정 · 롱/숏", sub: "코인마다 · 작은 선 = 지난 기록", cls: "s2-mkcard"}, boardBox, stamp,
      ui.disclosure("칸마다 뜻 (더 보기)", h("dl", {class: "lv-explain"}, EXPLAIN.map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, v)))))),
    ui.note("대시보드 서버가 바이낸스 공개 시세(키 없음)를 읽어 잠시 보관합니다. 이 화면은 우리 서버에만 묻습니다. 주문은 넣지 않습니다."));

  let mkt = null, live = null, failed = false;
  const liveOf = (c) => (live && (live.coins || []).find((x) => x.coin === c)) || null;
  const mktOf = (c) => (mkt && (mkt.coins || []).find((x) => x.coin === c)) || null;

  // ---------------------------------------------------------------- the coin tiles (built once, updated in place)
  const tiles = new Map();
  function tile(c) {
    const chg = h("span", {class: "num"});
    const price = h("b", {class: "num s2-mkpx"});
    const dot = h("i", {class: "s2-mkdot"});
    const lo = h("span", {class: "num"}), hi = h("span", {class: "num"});
    const fund = h("b", {class: "num"}), next = h("b", {class: "num", dataset: {cd: ""}}), oi = h("b", {class: "num"}), ls = h("b", {class: "num"});
    const kv = (k, v) => h("span", {class: "s2-mkkv"}, h("span", null, k), v);
    const el2 = h("a", {class: "s2-mkt", href: ctx.href("terminal", c), title: `${fmt.coin(c)} 터미널에서 보기`},
      h("span", {class: "s2-mkth"}, h("b", null, fmt.coin(c)), chg),
      price,
      h("span", {class: "s2-mkrng", title: "24시간 가장 낮은 값 ↔ 가장 높은 값 (점 = 지금)"}, h("span", {class: "s2-mkbar"}, dot), h("span", {class: "s2-mklh"}, lo, hi)),
      kv("펀딩", fund), kv("다음 펀딩", next), kv("미결제약정", oi), kv("롱/숏", ls));
    return {el: el2, chg, price, dot, lo, hi, fund, next, oi, ls};
  }
  function paintTiles() {
    for (const c of COINS) {
      if (!tiles.has(c)) tiles.set(c, tile(c));
      const t = tiles.get(c), l = liveOf(c), m = mktOf(c);
      const p = l && l.ok ? l : m && m.ok ? m : null;
      const ch = p ? p.change_pct : null;
      t.chg.textContent = fmt.pct(ch, true, 2);
      t.chg.className = ["num", fmt.tone(ch, t.chg.textContent)].join(" ");
      t.el.dataset.tone = fmt.tone(ch, t.chg.textContent) || "";
      K4.tickPrice(t.price, p ? p.price : null, p ? K.px(p.price) : "—", c);
      const low = l && l.low != null ? Number(l.low) : null, high = l && l.high != null ? Number(l.high) : null;
      const ok = p && low != null && high != null && high > low;
      t.dot.hidden = !ok;
      if (ok) t.dot.style.setProperty("--x", `${(Math.max(0, Math.min(1, (Number(p.price) - low) / (high - low))) * 100).toFixed(1)}%`);
      t.lo.textContent = low != null ? K.px(low) : "—";
      t.hi.textContent = high != null ? K.px(high) : "—";
      const rate = l && l.funding_rate != null ? l.funding_rate : m && m.funding_rate;
      t.fund.textContent = K.fundPct(rate);
      t.fund.className = ["num", Math.abs(Number(rate)) >= FUND_HOT ? "warn-t" : ""].join(" ");
      const nx = (l && l.next_funding_ms) || (m && m.next_funding_ms);
      t.next.dataset.cd = String(nx || "");
      t.next.textContent = K.countdown(nx);
      const usd = m && m.ok ? (m.oi_value_usd != null ? m.oi_value_usd : m.open_interest != null && m.price ? m.open_interest * m.price : null) : null;
      t.oi.textContent = usd != null ? `$${K.usdKo(usd)}` : "—";
      t.ls.textContent = m && m.ok && m.ls_now != null ? `${fmt.num(m.ls_now, 2)} (롱 ${fmt.ratio(m.long_share, 0)})` : "—";
    }
    if (tilesBox.childElementCount !== COINS.length) put(tilesBox, COINS.map((c) => tiles.get(c).el));
  }

  // ---------------------------------------------------------------- the derivatives board (v4 mk-fr rows)
  function paintBoard() {
    const rows = COINS.map((c) => ({coin: c, m: mktOf(c), l: liveOf(c)}));
    const head = h("div", {class: "s2-mfr s2-mfh", "aria-hidden": "true"}, h("span", null, "코인"), h("span", null, "펀딩 · 지난 세 번"),
      h("span", null, "미결제약정 · 24시간"), h("span", null, "롱/숏 계정 비율 · 24시간"));
    put(boardBox, h("div", {class: "s2-mfrs", role: "list"}, head, rows.map((r) => {
      const m = r.m;
      const rate = (r.l && r.l.funding_rate != null) ? r.l.funding_rate : m && m.funding_rate;
      const hist = m && m.funding ? m.funding : [];
      const usd = m && m.ok ? (m.oi_value_usd != null ? m.oi_value_usd : m.open_interest != null && m.price ? m.open_interest * m.price : null) : null;
      return h("div", {class: "s2-mfr", role: "listitem"},
        h("a", {class: "s2-mfc", href: ctx.href("terminal", r.coin), title: "터미널에서 보기"}, fmt.coin(r.coin)),
        h("span", {class: "s2-mfv", dataset: {k: "펀딩"}},
          h("b", {class: ["num", Math.abs(Number(rate)) >= FUND_HOT ? "warn-t" : ""]}, K.fundPct(rate)),
          hist.length ? h("span", {class: "lv-msp", title: hist.map((x) => `${fmt.kst(x[0])} ${K.fundPct(x[1])}`).join("\n")},
            K.spark(hist, {w: 60, h: 22, zero: true, dots: true, label: "지난 세 번의 펀딩"})) : null),
        h("span", {class: "s2-mfv", dataset: {k: "미결제약정"}}, !m || !m.ok ? h("span", {class: "muted"}, "—") : [
          h("b", {class: "num"}, `$${K.usdKo(usd)}`),
          h("small", {class: ["num", fmt.tone(m.oi_change_24h_pct)]}, fmt.pct(m.oi_change_24h_pct, true, 1)),
          h("span", {class: "lv-msp"}, K.spark(m.oi_hist || [], {w: 90, h: 22, area: true, cls: Number(m.oi_change_24h_pct) >= 0 ? "up" : "down", label: "지난 24시간 미결제약정"}))]),
        h("span", {class: "s2-mfv", dataset: {k: "롱/숏"}}, !m || !m.ok || m.ls_now == null ? h("span", {class: "muted"}, "—") : [
          h("b", {class: "num"}, fmt.num(m.ls_now, 2)),
          h("small", {class: "muted num"}, `(롱 ${fmt.ratio(m.long_share, 0)})`),
          h("span", {class: "lv-msp"}, K.spark(m.ls_ratio || [], {w: 90, h: 22, label: "지난 24시간 롱/숏 계정 비율"}))]));
    })));
  }

  function paint() {
    if (!mkt && !live) { put(say, failed ? ui.errorBox({status: 0}, load) : ui.empty("불러오는 중")); return; }
    if ((mkt && mkt.off) || (live && live.off)) {
      put(say, h("div", {class: "dl-missing"}, h("b", null, "꺼짐"), h("span", null, " · 실시간 시세가 꺼져 있습니다 (DEMOBOT_DASH_LIVE=off).")));
      put(tilesBox); put(boardBox, ui.none("꺼짐 · 실시간 시세가 꺼져 있어 펀딩 · 미결제약정 · 롱/숏도 없습니다")); return;
    }
    const rows = COINS.map((c) => ({m: mktOf(c), l: liveOf(c)}));
    if (rows.every((r) => !(r.m && r.m.ok) && !(r.l && r.l.ok))) {
      put(say, h("div", {class: "dl-missing"}, h("b", null, "준비 중"), h("span", null, " · 바이낸스 시세를 아직 받지 못했습니다. 잠시 뒤 다시 받습니다.")));
      put(tilesBox); put(boardBox); tiles.clear();
      return;
    }
    put(say);
    paintTiles();
    paintBoard();
    stamp.textContent = mkt && mkt.generated_ms ? `펀딩 · 미결제약정 · 롱/숏: ${fmt.hms(mkt.generated_ms)} KST에 받은 값${mkt.stale ? " (새로 받지 못해 예전 값)" : ""}` : "";
  }
  async function load() {
    try { mkt = await ctx.api("/api/market"); failed = false; } catch (e) { if (e && e.name === "AbortError") return; failed = true; }
    paint();
  }
  async function loadLive() {
    try { live = await ctx.api("/api/live"); } catch (e) { if (e && e.name === "AbortError") return; }
    liveLine.textContent = `가격: ${K.liveNote(live)}`;
    if (mkt || live) { if (tiles.size && !(live && live.off)) paintTiles(); else paint(); }
  }
  paint();
  await Promise.all([loadLive(), load()]);
  ctx.every(10000, loadLive);
  ctx.every(60000, load);
  ctx.every(1000, async () => { for (const b of el.querySelectorAll("[data-cd]")) b.textContent = K.countdown(Number(b.dataset.cd) || null); });
}

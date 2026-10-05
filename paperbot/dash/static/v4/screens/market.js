// #/market — 시장 (builder B, CONTRACT.md §4, INVENTORY §4 and the 오늘·일정 panel of §2). Outside context only:
// fear & greed, dominance and total market cap, the US indexes with 5-day lines, the US macro calendar with D-days,
// today and the schedule (funding, US market, next verdict, observation end), and GH Coin's current calls while its
// recorder runs. Nothing here feeds the paper accounts; the screen says so.
import {h, ui, fmt, store, motion, bars, serverNow, features} from "../core/pb.js";
import {countdown, fundPct} from "./positions-book.js";

const GH_KO = {long: "롱 타점", short: "숏 타점", longWait: "롱 대기", shortWait: "숏 대기", wait: "관망"};
const GH_TONE = {long: "up", longWait: "up", short: "down", shortWait: "down"};
const kday = (ms) => Math.floor((Number(ms) + 9 * 3.6e6) / 864e5);           // Korea calendar day
const dday = (ms, now) => { const d = kday(ms) - kday(now); return d < 0 ? "지남" : d === 0 ? "오늘" : `D-${d}`; };
const bigUsd = (x) => (x == null ? "—" : x >= 1e12 ? `${fmt.num(x / 1e12, 2)}조 달러` : x >= 1e9 ? `${fmt.num(x / 1e9, 1)}B 달러` : `${fmt.num(x, 0)} 달러`);

export async function mount(el, ctx) {
  ctx.setTitle("시장");
  const top = h("div", {class: "market-grid"}, motion.shimmer(3, true));
  const idx = h("div", {class: "market-idx"});
  const today = h("div", {class: "stack tight"});
  const cal = h("div", {class: "stack tight"});
  const gh = h("div", {class: "stack tight"});
  const ghCard = ui.card({plate: "GH Coin 지금 판단", sub: "기록만 하는 참고용 · 계좌와 무관"}, gh);
  el.append(ui.screenHead("시장", "바깥 시장 분위기 · 참고용"),
    top,
    h("div", {class: "market-cols"},
      h("div", {class: "stack"}, ui.card({plate: "미국 지수", sub: "5일 흐름 · 장이 열린 시간에만 움직임"}, idx),
        ui.card({plate: "미국 경제발표 일정", sub: "한국 시각 · 발표 앞뒤로 변동성이 커지는 때"}, cal)),
      h("div", {class: "stack"}, ui.card({plate: "오늘·일정", sub: "한국 시각 0시부터"}, today), ghCard)),
    h("p", {class: "pos-note"}, "이 화면은 바깥 공개 자료입니다. 무료 자료라 늦거나 비어 있을 수 있고, 모의 계좌의 매매에는 쓰이지 않습니다."));
  ghCard.hidden = !features.ghcoin;

  // ---------------------------------------------------------------- /api/market
  let mk = null;
  const prevNum = new Map();          // key -> the number shown last time (counts from there on a real change)
  const drawn = new Set();
  const drawOnce = (key, el) => { if (!drawn.has(key) && el instanceof SVGElement) { drawn.add(key); motion.drawIn(el, 700); } return el; };
  const nf = (key, v, o) => { const el = ui.numFrom(prevNum.get(key), v, o); if (v != null) prevNum.set(key, v); return el; };
  const stale = (x) => (x && x.stale ? ui.pill("예전 값", "thin", "새 값을 받지 못해 마지막 값을 보여 줍니다") : null);
  const miss = (x, what) => h("p", {class: "muted"}, `${what}를 받지 못했습니다`, x && x.error ? ` (${x.error})` : "");
  function renderTop() {
    const d = mk || {};
    const f = d.fng || {}, fn = f.now;
    const fTone = (v) => (v == null ? "" : v < 45 ? "down" : v > 55 ? "up" : "");
    const fng = ui.card({plate: "공포·탐욕 지수", sub: "alternative.me"},
      fn ? [h("div", {class: "market-big"}, nf("fng", fn.value, {format: "int", cls: fTone(fn.value)}), h("small", null, "/100"),
        h("span", {class: "market-lbl"}, fn.label_ko || ""), stale(f)),
        h("div", {class: "market-fbar", role: "img", "aria-label": `공포·탐욕 ${fn.value}`}, h("i", {style: {left: `${Math.max(0, Math.min(100, fn.value))}%`}})),
        h("div", {class: "market-fscale"}, h("span", null, "극단적 공포"), h("span", null, "중립"), h("span", null, "극단적 탐욕")),
        ui.kv([["어제", f.yesterday ? `${fmt.int(f.yesterday.value)} · ${f.yesterday.label_ko || ""}` : "—"],
          ["1주 전", f.week ? `${fmt.int(f.week.value)} · ${f.week.label_ko || ""}` : "—"]])] : miss(f, "공포·탐욕 지수"));
    const g = d.global || {};
    const dom = ui.card({plate: "도미넌스", sub: "CoinGecko"},
      g.btc_dom != null ? [h("div", {class: "market-big"}, nf("dom", g.btc_dom, {format: (v) => fmt.pctOf(v, 1)}), h("span", {class: "market-lbl"}, "비트코인 도미넌스"), stale(g)),
        ui.kv([["이더리움", fmt.pctOf(g.eth_dom, 1)], ["코인 전체 시가총액", bigUsd(g.total_mcap)],
          ["24시간", h("span", {class: fmt.tone(g.mcap_chg_24h)}, g.mcap_chg_24h == null ? "—" : fmt.pctOf(g.mcap_chg_24h, 2, true))]])] : miss(g, "도미넌스"));
    top.replaceChildren(fng, dom);
    idx.replaceChildren(...((d.indexes || []).length ? d.indexes.map((x) => h("div", {class: "market-ix"},
      h("div", {class: "market-ix-h"}, h("b", null, x.name || x.symbol), h("small", {class: "muted"}, x.symbol), stale(x)),
      x.price != null ? [h("div", {class: "market-ix-px"}, nf("ix:" + x.symbol, x.price, {format: x.symbol === "^TNX" ? (v) => fmt.pctOf(v, 3) : (v) => fmt.num(v, 2)}),
        h("span", {class: ["num", fmt.tone(x.chg)]}, x.chg == null ? "" : fmt.pct(x.chg, 2))),
        drawOnce("ix:" + x.symbol, ui.sparkline((x.points || []).map((p) => p[1]), {w: 220, h: 40, label: `${x.name} 5일 흐름`})),
        h("small", {class: "muted"}, x.ts ? `마지막 ${fmt.kst(x.ts)}` : "")] : miss(x, x.name || x.symbol))) : [ui.empty("지수 자료가 없습니다")]));
    const now = serverNow();
    const evs = d.events || [];
    cal.replaceChildren(...(evs.length ? evs.slice(0, 16).map((e) => {
      const past = e.ts_ms < now, dd = dday(e.ts_ms, now);
      return h("div", {class: ["lrow", "market-ev", past ? "past" : ""], role: "listitem"}, h("span", {class: "rk"}, fmt.kst(e.ts_ms)),
        h("span", {class: "lname"}, e.name_ko || e.kind), h("span", {class: ["ret", dd === "오늘" ? "accent" : ""]}, dd));
    }) : [ui.empty("등록된 일정이 없습니다")]),
    (d.events_problems || []).length ? h("p", {class: "down pos-note"}, `일정 파일에서 읽지 못한 줄: ${d.events_problems.join(" · ")}`) : null);
  }
  async function loadMarket() {
    try { mk = await ctx.api("/api/market"); if (ctx.alive()) renderTop(); }
    catch (e) { if (!(e && e.name === "AbortError") && !mk) top.replaceChildren(ui.errorBox(e, loadMarket)); }
  }

  // ---------------------------------------------------------------- 오늘·일정 (summary + ticker + clocks)
  const fundEl = h("b", {class: "num"}, "—"), usEl = h("b"), sessEl = h("b");
  let fundT = null, sum = null;
  function renderToday() {
    const s = sum, now = serverNow();
    const t = s && s.today;
    const ev = (s && s.events) || [];
    today.replaceChildren(
      t ? ui.kv([["청산된 거래 (전체)", `${fmt.int(t.trades)}건`],
        ["기존 36 손익 합계 (USDT)", h("span", {class: fmt.tone(t.pnl)}, fmt.money(t.pnl, true))],
        ["기존 36 이긴 거래", `${fmt.int(t.wins)} / ${fmt.int(t.strategy_trades)}`],
        ["강제청산", h("span", {class: t.liquidations ? "down" : ""}, `${fmt.int(t.liquidations)}건`)]]) : motion.shimmer(2),
      t ? ui.assume("closed", "손익 합계는 기존 36개 매매법 계좌만 (다른 묶음은 순위표에서)") : null,
      h("div", {class: "market-sched"},
        h("div", null, h("span", null, "다음 펀딩 (BTC)"), fundEl),
        h("div", null, h("span", null, "미국 증시"), usEl),
        h("div", null, h("span", null, "지금 시간대"), sessEl),
        ...ev.slice(0, 3).map((e) => h("div", null, h("span", null, e.name_ko || e.kind), h("b", null, `${fmt.kst(e.ts_ms)} (${dday(e.ts_ms, now)})`))),
        s && !ev.length ? h("div", null, h("span", null, "미국 경제발표"), h("b", {class: "muted"}, "등록된 일정 없음")) : null,
        s && s.next_checkpoint ? h("div", null, h("span", null, `${fmt.int(s.next_checkpoint.day)}일째 판정`),
          h("b", null, `${fmt.kst(s.next_checkpoint.ts)} (${dday(s.next_checkpoint.ts, now)})`)) : null,
        s && s.observing ? h("div", null, h("span", null, "관찰 기간 끝"), h("b", null, fmt.kst(s.observe_until))) : null));
    tick();
  }
  function tick() {
    const now = serverNow();
    const tk = store.get("ticker"), b = tk && tk.BTCUSDT;
    fundT = b && b.T;
    fundEl.replaceChildren(fundT ? `${countdown(fundT)} 뒤 · ` : "—", b ? h("span", {class: fmt.tone(-Number(b.r || 0))}, fundPct(b.r)) : "");
    const us = bars.usMarket(now), ss = bars.session(now);
    usEl.textContent = us.text; usEl.className = us.open ? "up" : "";
    sessEl.textContent = `${ss.weekend ? "주말 · " : ""}${ss.ko}`;
  }

  // ---------------------------------------------------------------- GH Coin (only while its recorder runs)
  async function loadGh() {
    if (!features.ghcoin) { ghCard.hidden = true; return; }
    ghCard.hidden = false;
    let g = null;
    try { g = await ctx.api("/api/ghcoin/board"); } catch (e) { g = null; }
    if (!ctx.alive()) return;
    if (!g || !g.coins || !Object.keys(g.coins).length) { gh.replaceChildren(ui.empty("GH Coin 기록기 응답 없음")); return; }
    gh.replaceChildren(...bars.TRADE_SYMS.map((s) => {
      const c = g.coins[s];
      if (!c) return h("div", {class: "lrow"}, h("span", {class: "rk"}, fmt.coin(s)), h("span", {class: "lname muted"}, (g.errors || {})[s] ? "가격 못 받음" : "—"), h("span"));
      const r = (c.rating || {})["240"] || (c.rating || {})["60"];
      return h("div", {class: "lrow", role: "listitem"}, h("span", {class: "rk"}, fmt.coin(s)),
        h("span", {class: ["lname", GH_TONE[c.state] || "muted"]}, GH_KO[c.state] || c.state || "—"),
        h("span", {class: "ret num"}, c.conf == null ? "—" : `확신 ${fmt.int(c.conf)}`),
        h("span", {class: "meta"}, r && r.label ? h("span", {class: r.all > 0 ? "up" : r.all < 0 ? "down" : ""}, `지표 ${r.label}`) : null,
          c.regime ? h("span", null, c.regime) : null, c.why ? h("span", null, c.why) : null));
    }), h("p", {class: "pos-note"}, g.alive ? "5분마다 갱신" : "기록기가 15분 넘게 조용합니다"));
  }

  ctx.watch("summary", (s) => { if (s) { sum = s; renderToday(); } });
  ctx.watch("ticker", () => tick());
  ctx.on("features", () => loadGh());
  ctx.every(1000, tick, {now: false});
  ctx.every(120000, loadMarket, {now: false});
  ctx.every(300000, loadGh, {now: false});
  renderToday();
  await Promise.all([loadMarket(), loadGh(), store.need("summary", 60000).catch(() => null)]);
}

export function unmount() {}

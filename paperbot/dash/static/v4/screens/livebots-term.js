// 실거래 › 요약 = the 실거래 터미널 (owners 10/19, their screenshot of the rule bot's #/terminal: "이런 느낌으로, 대신 진짜 실거래봇
// 대시보드니까"). The same frame and the same parts as screens/terminal.js, fed with the live bots' records:
//   top     the coin, its big price, 24 h, funding, open interest, long / short, range, 급등 · 급락 · 음펀비 and the KST clock
//           (terminal-top.js, the market's numbers), then the 실거래 strip: 바이비트 잔고 · MEXC 잔고 · 오늘 실거래 손익 ·
//           신호등 · 멈춤 · 40번 판단까지 (livebots-parts.js bandLine)
//   left    실시간 큰 체결 and 시장 강제청산 (the market, unchanged), 실거래 체결 (페이퍼 · 바이비트 · MEXC entries and exits)
//   centre  the coin strip (price, 24 h and each account's position on that coin), the chart (terminal-chart.js with the
//           live positions: entry, stop / lock, first stop, next ladder step; the marks of the accounts' recent trades; the
//           Premium / Discount light and blink, a flash when a live bot really fills on that coin), the table 포지션 / 체결 /
//           손절 주문 of the three accounts
//   right   이 코인 포지션 and 수익 차트 (terminal-pnl.js: per account, 24시간 / 7일 / 전체, 오늘 수익, 수익 캘린더)
//   below   the three accounts' LED balance bars, the two signal lights, the executors' WARN / CRITICAL console
// HONESTY: what the terminal promised stays true here: every glow answers a real change, nothing moves under reduced motion
// or on a hidden page, no order buttons; paper money (모의) and real money (실거래) each carry their own caption and are
// never added together.
import {h, ui, store, local, motion, bars, features, consolePanel} from "../core/pb.js";
import {topBar} from "./terminal-top.js";
import {watchList, liqFeed} from "./terminal-feed.js";
import {termChart} from "./terminal-chart.js";
import {pnlPanel} from "./terminal-pnl.js";
import {ages, MARKET_LABEL} from "./terminal-kit.js";
import {tickStream, bigFeed} from "./terminal-live.js";
import {bandLine, fillsPanel, coinMarks, minePanel, tablePanel} from "./livebots-parts.js";
import {liveLines, acctCard, lightRow, acctKo, paperSinceNote} from "./livebots-kit.js";
import {posKeys} from "./livebots-calc.js";

const PNL_IDS = ["bybit", "mexc", "paper"];
const LIVE_TF = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

/** termView(ctx, src) -> {el, set(d, state)}; src: {state() -> "loading" | "ok" | "failed", at() -> ms of the last good answer,
 *  retry()}: the screen loads /api/v4/livebots and hands every answer (or failure) to set(). */
export function termView(ctx, src) {
  const st = {sym: local.get("lb-sym", "BTCUSDT"), tf: local.get("lb-tf", "15m"), d: null, state: "loading"};
  if (!bars.SYMS.includes(st.sym)) st.sym = "BTCUSDT";
  if (!LIVE_TF.includes(st.tf)) st.tf = "15m";
  const q = ctx.params.query || {};
  if (q.sym && bars.SYMS.includes(q.sym)) st.sym = q.sym;

  const pick = (s) => {
    if (!bars.SYMS.includes(s) || s === st.sym) return;
    st.sym = s; local.set("lb-sym", s);
    top.setSym(s); watch.setSym(s); chart.setSym(s); mine.setSym(s); liq.setSym(s); table.setSym(s);
  };
  const acct = (id) => (st.d ? (st.d.accts || []).find((a) => a.id === id) : null);

  // ---- the parts (the terminal's own where they show the market, livebots-parts.js where they show our three accounts)
  const top = topBar(ctx, st, {meetings: false});       // (its AI meetings line is replaced by the live strip below)
  const perp = top.el.querySelector(".term-perp");
  if (perp) perp.textContent = "무기한 · 바이낸스 시세";
  const meet = top.el.querySelector(".term-mline");             // (the AI meetings line is the rule bot's: the live strip takes its place)
  const band = bandLine(ctx);
  if (meet) meet.replaceWith(band.el); else top.el.append(band.el);
  const marks = coinMarks();
  const watch = watchList(ctx, st, pick, {marks});
  const big = bigFeed(ctx);
  const liq = liqFeed(ctx, st, (fresh) => { for (const r of fresh || []) chart.onLiq(r); });
  const fills = fillsPanel(ctx);
  const chart = termChart(ctx, st, (tf) => { st.tf = tf; local.set("lb-tf", tf); }, {
    key: "live", label: "실거래 차트",
    keyTitle: "페이퍼(연습, P) · 바이비트(B) · WOO X Pro(W)의 진입선, 손절·잠금선, 페이퍼의 첫 손절과 다음 잠금 자리 (설정의 계단 잠금대로) · 왼쪽 이름표를 누르면 그 선만 숨김",
    more: (sym, tf) => ctx.href("livebots", "chart", {sym, tf}),
    lines: (sym, mark) => liveLines(st.d ? st.d.accts : [], sym, mark),
    posKeys: (sym) => posKeys(st.d ? st.d.accts : [], sym),
    trades: (sym) => (st.d ? (st.d.marks || []).filter((m) => m.symbol === sym) : []),
  });
  const mine = minePanel(ctx, st);
  const table = tablePanel(ctx, st, pick);
  let pnlId = local.get("lb-pnl-acct", "bybit");
  if (![...PNL_IDS, "paper2"].includes(pnlId)) pnlId = "bybit";
  const pickPnl = (id) => { pnlId = id; local.set("lb-pnl-acct", id); pnl.refresh(true); };
  const psegOf = (ids) => {
    const x = ui.seg(ids.map((id) => ({id, label: acctKo(id)})), ids.includes(pnlId) ? pnlId : "bybit", pickPnl, {label: "수익 차트 계좌"});
    x.classList.add("lb-pseg");
    return x;
  };
  let pseg = psegOf(PNL_IDS), psegKey = PNL_IDS.map((id) => `${id}:${acctKo(id)}`).join();
  const psegBox = h("span", {class: "lb-segbox"}, pseg);          // the switch is rebuilt in here (pnlIds)
  /** The P&L chart's accounts: the second paper bot too while the summary has it (owners 10/23), named by its bot. */
  function pnlIds(d) {
    const ids = d && (d.accts || []).some((a) => a.id === "paper2") ? [...PNL_IDS, "paper2"] : PNL_IDS;
    if (d && !ids.includes(pnlId)) pnlId = "bybit";
    const key = ids.map((id) => `${id}:${acctKo(id)}`).join();
    if (key === psegKey) return;
    psegKey = key;
    const nx = psegOf(ids);
    psegBox.replaceChildren(nx);
    pseg = nx;
  }
  const pnl = pnlPanel(ctx, {
    who: () => acctKo(pnlId), key: () => pnlId, winKey: "lb-pnl-win", lead: psegBox, retry: () => src.retry(),
    info: `고른 계좌가 닫은 거래의 실현 손익 합 (열린 포지션 빼고, 아래 표에 따로) · 한국 시간 · 막대 = 그 시간(또는 그날) 손익 · 최대 낙폭 = 이 선이 그 전 최고점에서 가장 깊게 내려간 만큼 · `
      + `바이비트·WOO X Pro: ${ui.ASSUME_LIVE_KO} · 페이퍼: ${ui.ASSUME_KO}`,
    curve: () => { const a = acct(pnlId); return a && a.state === "ok" ? {start: a.start, now: st.d.now_ms, hours: a.hours || []} : null; },
    cal: () => { const a = acct(pnlId); return a && a.state === "ok" ? a.calendar || null : null; },
    state: () => { const a = acct(pnlId); return !st.d ? (st.state === "failed" ? "failed" : "loading") : !a ? "none" : a.state === "ok" ? (st.state === "failed" ? "failed" : "ok") : a.state === "error" ? "failed" : "none"; },
    at: () => src.at(),
  });

  // ---- the frame (terminal.css: .term, .term-grid, .term-col, .term-mid)
  const left = h("aside", {class: "term-col term-left", "aria-label": "실시간 큰 체결, 시장 강제청산, 실거래 체결"}, big.el, liq.el, fills.el);
  const mid = h("div", {class: "term-mid"}, watch.el, chart.el, table.el);
  const right = h("aside", {class: "term-col term-right", "aria-label": "이 코인 포지션과 수익"}, mine.el, pnl.el);
  const foot = h("div", {class: "term-foot lb-foot"}, ui.assumeLive("바이비트 · WOO X Pro"),
    ui.assumeLine(["closed", "open"], `페이퍼(P) · '시장' 표시 = 바이낸스 ${MARKET_LABEL}`));
  const root = h("div", {class: "term lb-term"}, top.el, h("div", {class: "term-grid"}, left, mid, right), foot);

  // ---- below the terminal: the three LED bars, the two lights, the executors' console
  const leds = {};
  const cards = h("div", {class: "lb-nowgrid"});
  const lights = h("div", {class: "lb-lgrid"});
  const con = consolePanel({title: "실행기 콘솔", tabs: [{id: "all", label: "전체"}, {id: "bybit", label: "바이비트"}, {id: "mexc", label: "WOO X Pro"}],
    foot: "실행기 두 개의 주의 · 긴급 기록 (멈춤, 신호등 빨강, 거래소 기록과 다름 …) · 거래소 요청 재시도는 뺌", maxHeight: "260px", max: 120});
  con.showEmpty("불러오는 중");
  const secHead = h("h2", {class: "lb-sec"}, "세 계좌");    // two paper bots: 네 계좌 (drawBelow)
  const below = h("div", {class: "lb-below"},
    secHead, cards,
    h("div", {class: "lb-pair2"},
      ui.card({title: "신호등", sub: "페이퍼의 최근 성적이 기준을 넘을 때만 새 진입을 따라가요", cls: "lb-lights"}, lights,
        ui.note("칸은 페이퍼의 닫힌 거래, 왼쪽이 오래된 것 · 이김 = 손익이 0보다 큼 (실행기와 같은 규칙) · 빨강이어도 페이퍼는 계속 거래하고, 다시 기준을 넘으면 실거래도 따라가요")),
      h("div", {class: "lb-con"}, con)));
  const el = h("div", {class: "lb-sum"}, h("h2", {class: "term-sr"}, "실거래 터미널"), root, below);

  const still = () => { root.dataset.still = document.hidden ? "1" : ""; };
  still();
  ctx.listen(document, "visibilitychange", still);
  const syncLiq = () => left.classList.toggle("has-liq", !!features.liq);
  syncLiq();
  ctx.on("features", () => { syncLiq(); watch.onFeatures(); liq.onFeatures(); });
  ctx.watch("ticker", (tk) => { if (!tk) return; top.onTicker(tk); watch.onTicker(tk); chart.onTicker(tk); mine.onTicker(); table.onTicker(); });
  ctx.every(1000, () => { top.tick(); chart.tick(); ages(left); }, {now: true});
  const ticks = tickStream(ctx);
  ticks.on((m) => {
    top.onRelay(m);
    for (const ev of Array.isArray(m.ev) ? m.ev : []) {
      if (!ev || typeof ev.s !== "string") continue;
      watch.onTick(ev);
      if (ev.s === st.sym) { top.onTick(ev); chart.onTick(ev); }
    }
    big.onMsg(m);
    if (!m.first && m.big && Array.isArray(m.big.rows)) for (const r of m.big.rows) if (r && r.s === st.sym) chart.onBig(r);
  });
  ticks.start();

  let sigBelow = null;
  function drawBelow(d) {
    const sig = JSON.stringify([d.accts.map((a) => [a.state, a.balance, a.initial, a.stale, a.halted, a.halt_reason, a.stats, a.curve, a.consecutive_losses,
      a.kill_file, a.as_of_ms && Math.floor(a.as_of_ms / 60000)]), d.execs.map((x) => [x.light, x.notes]), d.trend_bot, (d.checkpoint || {}).n]);
    if (sig === sigBelow) return;
    sigBelow = sig;
    const notesOf = (id) => (id === "paper" ? paperSinceNote(d) : ((d.execs || []).find((x) => x.id === id) || {}).notes);
    const nk = d.accts.length === 4 ? "네 계좌" : "세 계좌";
    if (secHead.textContent !== nk) secHead.textContent = nk;
    cards.replaceChildren(...d.accts.map((a) => acctCard(a, leds[a.id] || (leds[a.id] = ui.ledBar({label: `${acctKo(a.id)} 잔고`})), notesOf(a.id))));
    lights.replaceChildren(...(d.execs || []).map(lightRow));
  }
  let sigCon = null;
  function drawConsole(d) {
    const ev = (d.events || []).slice(0, 120);
    const sig = ev.map((e) => `${e.ex}:${e.id}`).join(",") + "|" + d.execs.map((x) => x.record.state).join(",");
    if (sig === sigCon) return;
    sigCon = sig;
    const unread = (d.execs || []).filter((x) => x.record.state !== "ok");
    con.setFoot(unread.length ? `${unread.map((x) => `${x.name_ko} 기록: ${x.record.state === "error" ? "못 읽음" : "수집 전"} (${x.record.reason_ko || ""})`).join(" · ")}`
      : "실행기 두 개의 주의 · 긴급 기록 (멈춤, 신호등 빨강, 거래소 기록과 다름 …) · 거래소 요청 재시도는 뺌");
    if (!ev.length) { con.setLines([]); con.showEmpty(unread.length === (d.execs || []).length ? "실행기 기록을 아직 못 읽었어요" : "주의 · 긴급 기록이 아직 없어요"); return; }
    con.setLines(ev.map((e) => ({id: `${e.ex}:${e.id}`, type: e.level === "CRITICAL" ? "bad" : "ev", tabs: [e.ex], ts: e.ts,
      text: `[${e.ex_ko} · ${e.level_ko}] ${e.kind_ko}: ${e.text}`})));
  }

  return {
    el,
    /** A new answer (d) or a failed refresh (d null, state "failed"): every part redraws only what changed. */
    set(d, state) {
      st.state = state;
      if (d) { st.d = d; pnlIds(d); }
      band.set(st.d, state);
      fills.set(st.d, state);
      watch.onBoard(st.d, state === "failed" && !st.d);
      mine.set(st.d, state);
      table.set(st.d, state);
      chart.refresh();
      pnl.refresh();
      if (st.d) { drawBelow(st.d); drawConsole(st.d); }
    },
    /** (livebots.js) a light turned red or an executor halted, really, since the last answer. */
    alarm(list) { band.alarm(list); },
  };
}

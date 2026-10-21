// 실거래 › 추세 차트 (#/tchart; owners 10/21 "대시보드 화면들 더 멋있게 모든 필요한 화면 부분들 다 추가로 만들어줘"): the
// 추세판단 봇's judgments over time and its signals on the price chart, read-only:
//   추세 흐름  a heatmap: the six coins × the 1시간 judgment (30m entries read it) and the 4시간 judgment (1h entries) over
//             the last 72 hours, one cell per closed bar, placed over the time its judgment was in force (from its bar's
//             close to the next close): 상승 / 하락 (a trend the bot takes), 보류 (a lighter tint of the side while 3 of 4
//             agree but the hold is not met: 유지 확인 중), 힘 약함 / 끝물 (hatched: no entry), 못 읽음 (grey); a dot =
//             a paper entry on the row it read, × = a supervisor exit (감독 청산). A row picks the coin of the chart; a
//             cell shows its numbers below (and on hover).
//   차트      the chosen coin's 30분 or 1시간 candles (/api/candles, ~150 bars shown), EMA20, a thin band under them in the
//             colour of the higher bar's judgment the bot read at each bar's close (tall = a trend it takes, short = no
//             entry), the coin's signals of the last 3 days by what became of them, the paper trades (entry ▲▼, exit ■
//             with its reason in words), a wait's pullback level as a dashed line, the crosshair's bar in words.
// Sources: /api/v4/livebots/trendchart?symbol= (dash/more/livetrendchart.py: the judgments recomputed bar by bar with the
// bot's own functions and numbers, checked against the bot's record; the signals, trades and waits of the paper bot both
// executors follow) every 30 s (a few seconds while bars are still coming in), and the site's /api/candles.
// HONESTY: a cell the bot could not have judged, or bars not received, = 못 읽음 / 불러오는 중 with the reason, never a
// colour of a guess; the recomputed judgment that differs from the bot's own record says so. Times in KST. The bot's start
// (``since``) is a line on the heat; the entries, exits and signals of the bot before it on the same paper account are
// dimmed and said to be 전환 전 (owners 10/21: the switch night still shows the old bot's last day).
import {h, put, ui, fmt, local, makeChart, candleOptions, tok, priceDec} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";

export const API = "/api/v4/livebots/trendchart";
const CANDLES = "/api/candles";
const REFRESH_MS = 30 * 1000;
const QUICK_MS = 4 * 1000;                 // while the server is still fetching bars (``pending``)
const HOUR = 3600 * 1000;
export const COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"];
const TF_MS = {"30m": 30 * 60 * 1000, "1h": HOUR, "4h": 4 * HOUR};
const HTF = {"30m": "1h", "1h": "4h"};
const ENTRY = {"1h": "30m", "4h": "1h"};
const ENTRY_TFS = [{id: "30m", label: "30분"}, {id: "1h", label: "1시간"}];
const SHOW_BARS = 150, FETCH_BARS = 300;  // EMA20 settles over the 150 bars before the ones shown
const JUDGES = [["V3.9", 0], ["EMA·DMI·ADX", 1], ["OBV", 2], ["일목·AO", 3]];
const SIDE = (s) => (Number(s) > 0 ? "롱" : "숏");
const ok = (x) => x != null && x !== "" && Number.isFinite(Number(x));
const two = (n) => String(n).padStart(2, "0");
export const EXIT_KO = {LOCK: "계단 익절", SL: "손절", REV: "빠른 청산", JUDGE: "감독(추세)", TIME: "감독(시간)", LIQ: "강제청산",
  HALT: "멈춤", MANUAL: "수동", END: "끝냄"};
export const exitKo = (r) => EXIT_KO[r] || String(r ?? "—");

// ---------------------------------------------------------------- pure (node tests: tests/test_livetrendchart.py)
/** {cls, word, sub, allow: {side, ko}} of one heat cell (``tf`` = the judged timeframe, 1h / 4h; ``rules`` the numbers). */
export function cellInfo(c, tf, rules) {
  const e = ENTRY[tf] === "30m" ? "30분" : "1시간";
  const r = rules || {};
  if (!c || c.kind === "na" || c.kind == null) {
    return {cls: "na", word: "못 읽음", sub: (c && c.why) || "봉을 아직 못 받음", allow: {side: 0, ko: `${e} 쉼 · 판단 못 읽음`}};
  }
  const [base, mod] = String(c.kind).split(" ");
  const adx = Number(c.adx), prev = Number(c.adx_prev);
  const bits = [`상승 ${fmt.int(c.up)}·하락 ${fmt.int(c.dn)}`];
  if (Number.isFinite(adx)) bits.push(`ADX ${Math.round(adx)} ${adx > prev ? "오름" : "내림"}`);
  if (base === "hold") {
    const lean = mod === "up" ? "상승" : mod === "down" ? "하락" : null;
    return {cls: mod ? `hold ${mod}` : "hold", word: lean ? `보류 (${lean} 유지 확인 중)` : "보류", sub: bits.join(" · "),
      allow: {side: 0, ko: `${e} 쉼 · 보류`}};
  }
  const side = base === "up" ? 1 : -1;
  const word = side > 0 ? "상승" : "하락";
  if (mod === "tired") {
    return {cls: `${base} tired`, word: `${word} · 끝물`, sub: `${bits.join(" · ")} · ADX ${fmt.int(r.adx_tired ?? 40)} 넘고 꺾임`,
      allow: {side: 0, ko: `${e} 쉼 · 끝물`}};
  }
  if (mod === "weak") {
    return {cls: `${base} weak`, word: `${word} · 힘 약함`, sub: `${bits.join(" · ")} · ADX ${fmt.int(r.adx_min ?? 20)} 미만`,
      allow: {side: 0, ko: `${e} 쉼 · 힘 약함`}};
  }
  return {cls: base, word, sub: bits.join(" · "), allow: {side, ko: `${e} ${SIDE(side)}만`}};
}
/** "▲" / "▼" / "–" of one judge's vote. */
export const voteMark = (v) => (Number(v) > 0 ? "▲" : Number(v) < 0 ? "▼" : "–");
/** The KST hour of a ms time (0..23). */
export const kstHour = (t) => Math.floor((Number(t) + 9 * HOUR) / HOUR) % 24;
/** The time axis labels of ``n`` hour columns from t0: every 6 hours KST, the date at midnight. */
export function hourTicks(t0, n) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const t = Number(t0) + i * HOUR, hr = kstHour(t);
    if (hr % 6) continue;
    out.push({i, day: hr === 0, ko: hr === 0 ? fmt.mmdd(t) : `${two(hr)}시`});
  }
  return out;
}
/** The cells of one row placed on the hour columns [t0, t1): [{c, col (0-based), span, now}] plus {gap: true, col, span}
 *  for the hours with no cell (bars not received). A cell is in force from its ``t`` for one bar of ``tf``. */
export function placeCells(cells, t0, t1, tf, now) {
  const ms = TF_MS[tf] || HOUR, n = Math.round((t1 - t0) / HOUR);
  const out = [];
  let at = 0;
  for (const c of cells || []) {
    const a = Math.max(0, Math.round((Number(c.t) - t0) / HOUR)), b = Math.min(n, Math.round((Number(c.t) + ms - t0) / HOUR));
    if (b <= a || a < at) continue;
    if (a > at) out.push({gap: true, col: at, span: a - at});
    out.push({c, col: a, span: b - a, now: now != null && Number(c.t) <= now && now < Number(c.t) + ms});
    at = b;
  }
  if (at < n) out.push({gap: true, col: at, span: n - at});
  return out;
}
/** Where a time sits across the heatmap (0..1), null outside it. */
export function markX(t, t0, t1) {
  const v = (Number(t) - t0) / (t1 - t0);
  return Number.isFinite(v) && v >= 0 && v <= 1 ? v : null;
}
/** The higher bar's judgment the bot read for an entry bar opening at ``openSec`` (s) of ``tf``: the last closed htf bar
 *  at that bar's close. ``byT``: Map cell t (ms) -> cell. */
export function bandAt(byT, openSec, tf) {
  const htf = HTF[tf];
  if (!htf || !byT) return null;
  const close = Number(openSec) * 1000 + TF_MS[tf], hm = TF_MS[htf];
  return byT.get(close - (close % hm)) || null;
}
/** The band bar of a judgment: {value (height 0..1), key (colour)}: tall = a trend the bot takes, short = no entry. */
export function bandBar(c) {
  if (!c || c.kind === "na") return null;
  const [base, mod] = String(c.kind).split(" ");
  if (base === "hold") return mod ? {value: 0.38, key: `${mod}-dim`} : {value: 0.2, key: "hold"};
  if (mod) return {value: 0.6, key: `${base}-dim`};
  return {value: 1, key: base};
}
/** EMA (pandas ewm span=n, adjust=False, min_periods=n: fg_indicators.ema, the bot's): null for the first n-1 values. */
export function ema(values, n) {
  const a = 2 / (n + 1), out = [];
  let e = null;
  values.forEach((v, i) => {
    e = e == null ? Number(v) : a * Number(v) + (1 - a) * e;
    out.push(i >= n - 1 ? e : null);
  });
  return out;
}
/** How a signal is drawn: {shape, key (colour), text, title}. */
export function sigMark(s) {
  const long = Number(s.side) > 0;
  const base = {position: long ? "belowBar" : "aboveBar", shape: "circle"};
  const k = s.kind;
  if (k === "entered") return {...base, key: long ? "up" : "down", text: "", title: "진입한 신호"};
  if (k === "touched") return {...base, key: long ? "up-dim" : "down-dim", text: "", title: "되돌림 닿음 · 진입 안 됨"};
  if (k === "wait") return {...base, key: "warn", text: "", title: "되돌림 기다림"};
  if (k === "nopull") return {...base, key: "muted", text: "", title: "되돌림 안 옴"};
  if (k === "blocked") return {...base, key: "muted", text: "×", title: s.cat === "trend" ? "추세 판단에 걸림" : "진입 자리 검사에 걸림"};
  if (k === "prev") return {...base, key: "line", text: "", title: "전환 전 · 예전 봇 신호"};
  return {...base, key: "line", text: "×", title: s.cat_ko || "다른 이유"};
}
/** The chart's markers for the coin's signals (of this entry timeframe), the paper trades and the open position, each on
 *  the bar that holds it (``times``: Set of the candles' open seconds); sorted by time. Colours as keys. */
export function chartMarks(c, tf, times) {
  const ms = TF_MS[tf], out = [];
  const at = (t) => { const s = Math.floor((Number(t) - (Number(t) % ms)) / 1000); return times.has(s) ? s : null; };
  for (const s of (c && c.signals) || []) {
    if (s.tf !== tf) continue;
    const time = at(Number(s.t) - ms);                     // the signal's bar: it closed at s.t
    if (time == null) continue;
    const m = sigMark(s);
    out.push({time, position: m.position, shape: m.shape, key: m.key, text: m.text, size: 0.7, ord: 0});
  }
  const trades = [...((c && c.trades) || [])];
  if (c && c.position) trades.push({...c.position, open: true});
  for (const x of trades) {
    const long = Number(x.side) > 0;
    const te = at(x.entry_time);
    if (te != null) out.push({time: te, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown",
      key: long ? "up" : "down", text: `${x.before ? "전환 전 " : ""}진입 ${SIDE(x.side)}`, ord: 1});
    if (x.open) continue;
    const tx = at(x.exit_time);
    if (tx != null) out.push({time: tx, position: long ? "aboveBar" : "belowBar", shape: "square",
      key: Number(x.roe) > 0 ? "up" : "down", text: exitKo(x.reason), ord: 2});
  }
  return out.sort((a, b) => a.time - b.time || a.ord - b.ord);
}
/** The coins taking entries now on one judged timeframe: ["BTC 롱", ...] from each row's cell in force now. */
export function takingNow(heat, tf, now, rules) {
  const out = [];
  for (const sym of COINS) {
    const row = ((heat && heat.coins && heat.coins[sym]) || {})[tf];
    if (!row || row.state !== "ok") continue;
    const c = (row.cells || []).find((x) => Number(x.t) <= now && now < Number(x.t) + TF_MS[tf]);
    const a = cellInfo(c, tf, rules).allow;
    if (a.side) out.push(`${fmt.coin(sym)} ${SIDE(a.side)}`);
  }
  return out;
}
/** The rows checked against the bot's own record: {same, differs, of}. */
export function checkCount(heat) {
  const out = {same: 0, differs: 0, of: 0, list: []};
  for (const sym of COINS) {
    for (const tf of ["1h", "4h"]) {
      const row = ((heat && heat.coins && heat.coins[sym]) || {})[tf];
      if (!row || !row.check) continue;
      out.of += 1;
      out[row.check] += 1;
      if (row.check === "differs") out.list.push(`${fmt.coin(sym)} ${fmt.tfKo(tf)} (봇 기록: ${row.bot || "—"})`);
    }
  }
  return out;
}

// ---------------------------------------------------------------- the view
/** tchartView(ctx) -> {el, set()}: its own endpoint every 30 s and the coin's candles; the summary is not needed. */
export function tchartView(ctx) {
  const q = (ctx.params && ctx.params.query) || {};
  const st = {sym: local.get("ltc-sym", "BTCUSDT"), tf: local.get("ltc-tf", "30m"), d: null, okAt: 0, busy: false, c: null,
    cKey: "", cErr: null, pin: null, hover: null, quick: null, fitKey: ""};
  if (q.sym && COINS.includes(q.sym)) st.sym = q.sym;
  if (!COINS.includes(st.sym)) st.sym = "BTCUSDT";
  if (!HTF[st.tf]) st.tf = "30m";
  const stateSlot = h("div", {class: "lb-slot"});
  // ---- 추세 흐름
  const nowChips = h("div", {class: "ltc-now", role: "list", "aria-label": "지금 진입 받는 방향"});
  const checkSlot = h("span", {class: "ltc-check"});
  const stamp = h("span", {class: "ltc-stamp"});
  const heatBox = h("div", {class: "ltc-heat", role: "group", "aria-label": "코인별 추세 판단 72시간"});
  const scroller = h("div", {class: "ltc-hscroll"}, heatBox);
  const read = h("div", {class: "ltc-read", "aria-live": "polite"});
  const heatCard = ui.card({title: "추세 흐름 · 최근 72시간", cls: "ltc-heatcard", acts: [checkSlot, stamp],
    sub: "끝난 봉의 판단만 · 칸 하나 = 그 판단이 쓰인 시간 · 줄을 누르면 아래 차트가 그 코인으로 바뀌어요"},
  nowChips, scroller, read, heatLegend());
  // ---- 차트
  const coinSeg = ui.seg(COINS.map((c) => ({id: c, label: fmt.coin(c)})), st.sym, (id) => pick(id, null), {label: "코인", scroll: true});
  const tfSeg = ui.seg(ENTRY_TFS, st.tf, (id) => pickTf(id), {label: "진입 봉"});
  const coinNow = h("div", {class: "ltc-coinnow"});
  const cread = h("div", {class: "ltc-cread", "aria-live": "polite"});
  const cbox = h("div", {class: "ltc-cbox", role: "img", "aria-label": "가격 차트"});
  const cslot = h("div", {class: "ltc-cslot"});
  const chartSub = h("span", {class: "sub"});
  const chartCard = h("section", {class: "card ltc-chartcard", "aria-label": "차트"},
    h("div", {class: "card-h"}, h("h2", null, "차트"), chartSub),
    h("div", {class: "ltc-ctrl"}, coinSeg, tfSeg), coinNow, cread, h("div", {class: "ltc-cwrap"}, cbox, cslot), chartLegend());
  const events = h("div", {class: "ltc-events"});
  const eventsCard = ui.card({title: "이 코인 최근 3일", sub: "신호는 봇이 남긴 이유 그대로 · 거래는 페이퍼(연습) · 한국 시간", cls: "ltc-evcard"}, events);
  const howCard = ui.card({title: "읽는 법", cls: "ltc-howcard"}, howTo());
  const cards = h("div", {class: "ltc-cards"}, heatCard, chartCard, h("div", {class: "ltc-two"}, eventsCard, howCard));
  const main = h("div", {class: "ltc-body"}, cards);
  const el = h("div", {class: "ltc stack"}, stateSlot, main,
    ui.note("보기만 하는 화면 · 판단은 봇과 같은 함수·같은 숫자로 봉마다 다시 계산 · 이 화면은 30초마다 새로 읽어요"));

  // ---------------------------------------------------------------- 추세 흐름
  function rules() { return (st.d && st.d.rules) || {}; }
  function drawHeat() {
    const d = st.d, heat = d.heat || {}, t0 = Number(heat.t0), t1 = Number(heat.t1), n = Number(heat.hours) || 72;
    const now = Number(d.now_ms);
    stamp.textContent = ok(d.ts) ? `봇 판단 ${fmt.kst(d.ts)} 기준` : "";
    const cc = checkCount(heat);
    put(checkSlot, cc.of ? ui.pill(cc.differs ? `봇 기록과 다름 ${cc.differs}줄` : `봇 기록과 같음 ${cc.same}/${cc.of}`,
      cc.differs ? "warn" : "good", cc.differs ? `다시 계산한 지금 칸이 봇이 남긴 판단과 달라요: ${cc.list.join(", ")}`
        : "다시 계산한 지금 칸이 봇이 남긴 판단(상승·하락·보류와 판단 4개)과 같아요") : null);
    const t30 = takingNow(heat, "1h", now, rules()), t1h = takingNow(heat, "4h", now, rules());
    put(nowChips,
      h("div", {class: ["ltc-nowi", t30.length ? "on" : ""], role: "listitem"}, h("span", {class: "ltc-nowk"}, "30분 진입 받는 곳 (1시간 판단)"),
        h("b", null, t30.length ? t30.join(" · ") : "없음 · 모두 쉼")),
      h("div", {class: ["ltc-nowi", t1h.length ? "on" : ""], role: "listitem"}, h("span", {class: "ltc-nowk"}, "1시간 진입 받는 곳 (4시간 판단)"),
        h("b", null, t1h.length ? t1h.join(" · ") : "없음 · 모두 쉼")));
    const marks = d.marks || {};
    // the trend bot's start: a line down every row (what is left of it is the bot before it, 전환 전)
    const sx = ok(d.since) ? markX(d.since, t0, t1) : null;
    // KST midnights: a thin line down every row
    const days = hourTicks(t0, n).filter((x) => x.day && x.i > 0).map((x) => x.i / n);
    const axis = h("div", {class: "ltc-axisrow", "aria-hidden": "true"}, h("div", {class: "ltc-lab"}),
      h("div", {class: "ltc-axis", style: {"--cols": n}}, hourTicks(t0, n).filter((x) => x.i < n - 6).map((x) => h("span", {class: ["ltc-tick", x.day ? "day" : ""],
        style: {"--x": (x.i / n).toFixed(4)}}, x.ko)),
        sx != null && sx < 0.93 ? h("span", {class: "ltc-tick start", style: {"--x": sx.toFixed(4)}}, "새 봇 시작") : null,
        h("span", {class: "ltc-tick now", style: {"--x": "1"}}, "지금")));
    const rows = COINS.map((sym) => {
      const row = (heat.coins || {})[sym] || {};
      const lines = ["1h", "4h"].map((tf) => {
        const r = row[tf] || {state: "pending", reason_ko: "불러오는 중"};
        if (r.state !== "ok") {
          return h("div", {class: ["ltc-cells", "ltc-off", r.state], style: {"--cols": n}, title: r.reason_ko || ""},
            h("span", {class: "ltc-offt"}, r.state === "pending" ? "불러오는 중" : `못 읽음 · ${r.reason_ko || ""}`));
        }
        const placed = placeCells(r.cells, t0, t1, tf, now);
        const kids = placed.map((p) => {
          const col = `${p.col + 1} / span ${p.span}`;
          if (p.gap) return h("i", {class: "ltc-c gap", style: {gridColumn: col}, title: "이 시간 봉을 아직 못 받음"});
          const x = cellInfo(p.c, tf, rules());
          const pinned = st.pin && st.pin.sym === sym && st.pin.tf === tf && st.pin.t === Number(p.c.t);
          return h("i", {class: ["ltc-c", x.cls, p.now ? "now" : "", pinned ? "pin" : ""], style: {gridColumn: col},
            dataset: {s: sym, tf, t: String(p.c.t)}, title: `${fmt.coin(sym)} ${fmt.tfKo(tf)} ${fmt.kst(p.c.t)} · ${x.word}`});
        });
        const dots = days.map((x) => h("i", {class: "ltc-day", style: {"--x": x.toFixed(4)}}));
        if (sx != null) dots.push(h("i", {class: "ltc-start", style: {"--x": sx.toFixed(4)}, title: `${fmt.kst(d.since)} 추세판단 봇 시작`}));
        for (const m of marks.entries || []) {
          if (m.symbol !== sym || m.htf !== tf) continue;
          const xx = markX(m.t, t0, t1);
          if (xx == null) continue;
          dots.push(h("i", {class: ["ltc-dot", Number(m.side) > 0 ? "long" : "short", m.open ? "open" : "", m.before ? "before" : ""],
            style: {"--x": xx.toFixed(4)}, title: `${m.before ? "전환 전 · " : ""}${fmt.kst(m.t)} 페이퍼 진입 ${fmt.coin(sym)} ${SIDE(m.side)} · `
              + `${fmt.stratKo(m.strategy)} ${fmt.tfKo(m.tf)}${m.open ? " · 보유 중" : ""}`}));
        }
        for (const m of marks.sup || []) {
          if (m.symbol !== sym || m.htf !== tf) continue;
          const xx = markX(m.t, t0, t1);
          if (xx == null) continue;
          dots.push(h("i", {class: ["ltc-x", m.reason === "TIME" ? "time" : "judge"], style: {"--x": xx.toFixed(4)},
            title: `${fmt.kst(m.t)} 감독 청산 ${fmt.coin(sym)} ${SIDE(m.side)} · ${m.reason_ko}${m.why ? ` · ${m.why}` : ""}`
              + (m.before ? " · 전환 전 포지션 (새 봇 성적엔 안 셈)" : "")}, "×"));
        }
        return h("div", {class: ["ltc-cells", r.stale ? "stale" : ""], style: {"--cols": n}, role: "presentation",
          title: r.stale ? r.reason_ko || "" : null}, kids, h("span", {class: "ltc-marks"}, dots));
      });
      const sel = sym === st.sym;
      const head = h("div", {class: "ltc-lab"},
        h("button", {type: "button", class: "ltc-name", "aria-pressed": String(sel), title: `${fmt.coin(sym)} 차트 보기`,
          onclick: () => pick(sym, null)}, fmt.coin(sym)),
        h("span", {class: "ltc-tf"}, "1시간"), h("span", {class: "ltc-tf"}, "4시간"));
      return h("div", {class: ["ltc-coin", sel ? "sel" : ""], role: "group", "aria-label": `${fmt.coin(sym)} 1시간·4시간 판단`},
        head, h("div", {class: "ltc-lines"}, lines));
    });
    const first = !heatBox.childNodes.length;
    put(heatBox, axis, rows);
    if (first && typeof requestAnimationFrame === "function") requestAnimationFrame(() => { scroller.scrollLeft = scroller.scrollWidth; });
    drawRead();
  }
  /** The cell under the pointer (or the one tapped), else the chosen coin now, in words. */
  function drawRead() {
    const d = st.d;
    if (!d || d.state !== "ok") { put(read); return; }
    const heat = d.heat || {}, now = Number(d.now_ms);
    const focus = st.hover || st.pin;
    const one = (sym, tf, c, title) => {
      const x = cellInfo(c, tf, rules());
      const marks = d.marks || {}, ms = TF_MS[tf];
      const inCell = c ? [...(marks.entries || []).filter((m) => m.symbol === sym && m.htf === tf && m.t >= c.t && m.t < c.t + ms)
        .map((m) => `${fmt.hm(m.t)} 페이퍼 진입 ${SIDE(m.side)} (${fmt.stratKo(m.strategy)} ${fmt.tfKo(m.tf)})`),
      ...(marks.sup || []).filter((m) => m.symbol === sym && m.htf === tf && m.t >= c.t && m.t < c.t + ms)
        .map((m) => `${fmt.hm(m.t)} ${m.reason === "TIME" ? "감독 청산(시간 정리)" : "감독 청산(추세 뒤집힘)"}`)] : [];
      return h("div", {class: ["ltc-ritem", x.cls.split(" ")[0]]},
        h("div", {class: "ltc-rhead"}, h("b", null, title || `${fmt.coin(sym)} · ${fmt.tfKo(tf)} 판단`),
          c ? h("span", {class: "ltc-rt num"}, `${fmt.kst(c.t)}에 끝난 봉 · ${fmt.hm(c.t)}~${fmt.hm(Number(c.t) + ms)}에 씀`) : null),
        h("div", {class: "ltc-rmain"}, h("b", {class: ["ltc-word", x.cls.split(" ")[0]]}, x.word),
          h("span", {class: ["ltc-allow", x.allow.side > 0 ? "up" : x.allow.side < 0 ? "down" : ""]}, x.allow.ko)),
        h("span", {class: "ltc-rsub"}, x.sub),
        c && c.votes ? h("span", {class: "ltc-votes"}, JUDGES.map(([ko, i]) => h("span", {class: ["ltc-vote", c.votes[i] > 0 ? "up" : c.votes[i] < 0 ? "down" : ""]},
          voteMark(c.votes[i]), h("i", null, ko)))) : null,
        inCell.length ? h("span", {class: "ltc-rmarks"}, inCell.join(" · ")) : null);
    };
    if (focus) {
      const row = ((heat.coins || {})[focus.sym] || {})[focus.tf] || {};
      const c = (row.cells || []).find((x) => Number(x.t) === focus.t);
      put(read, one(focus.sym, focus.tf, c), st.pin && !st.hover ? h("button", {type: "button", class: "linkish ltc-unpin",
        onclick: () => { st.pin = null; drawHeat(); }}, "지금으로") : null);
      return;
    }
    const row = (heat.coins || {})[st.sym] || {};
    put(read, ["1h", "4h"].map((tf) => {
      const r = row[tf] || {};
      const c = (r.cells || []).find((x) => Number(x.t) <= now && now < Number(x.t) + TF_MS[tf]);
      if (r.state !== "ok" || !c) {
        return h("div", {class: "ltc-ritem na"}, h("div", {class: "ltc-rhead"}, h("b", null, `${fmt.coin(st.sym)} · ${fmt.tfKo(tf)} 판단 지금`)),
          h("span", {class: "ltc-rsub"}, r.state === "pending" ? "불러오는 중" : r.reason_ko || "지금 칸을 아직 못 읽었어요"));
      }
      return one(st.sym, tf, c, `${fmt.coin(st.sym)} · ${fmt.tfKo(tf)} 판단 지금`);
    }));
  }
  const cellOf = (t) => {
    const n = t && t.closest ? t.closest(".ltc-c") : null;
    if (!n || !n.dataset || n.dataset.t == null) return null;
    return {sym: n.dataset.s, tf: n.dataset.tf, t: Number(n.dataset.t)};
  };
  heatBox.addEventListener("pointerover", (e) => {
    const c = cellOf(e.target);
    if (!c) return;
    if (st.hover && st.hover.sym === c.sym && st.hover.tf === c.tf && st.hover.t === c.t) return;
    st.hover = c; drawRead();
  });
  heatBox.addEventListener("pointerleave", () => { if (st.hover) { st.hover = null; drawRead(); } });
  heatBox.addEventListener("click", (e) => {
    const c = cellOf(e.target);
    if (!c) return;
    st.pin = c; st.hover = null;
    pick(c.sym, ENTRY[c.tf]);
  });

  // ---------------------------------------------------------------- 차트
  const C = {api: null, loading: null, candles: null, ema: null, band: null, lines: [], colors: null};
  function colors() {
    if (!C.colors) {
      C.colors = {up: tok("--up"), down: tok("--down"), "up-dim": tok("--up-line"), "down-dim": tok("--down-line"), hold: tok("--line-2"),
        accent: tok("--accent"), warn: tok("--warn"), muted: tok("--muted"), line: tok("--line-2"), ink2: tok("--ink-2")};
    }
    return C.colors;
  }
  function ensureChart() {
    if (C.api || C.loading) return C.loading || Promise.resolve(C.api);
    C.loading = makeChart(cbox, {rightPriceScale: {scaleMargins: {top: 0.08, bottom: 0.12}}, timeScale: {rightOffset: 3, barSpacing: 7}})
      .then((api) => {
        if (!ctx.alive()) { api.dispose(); return null; }
        ctx.track(api.dispose);
        const col = colors();
        C.api = api;
        C.band = api.chart.addHistogramSeries({priceScaleId: "band", base: 0, priceLineVisible: false, lastValueVisible: false,
          autoscaleInfoProvider: () => ({priceRange: {minValue: 0, maxValue: 1}})});
        api.chart.priceScale("band").applyOptions({scaleMargins: {top: 0.93, bottom: 0}, visible: false});
        C.ema = api.chart.addLineSeries({color: col.ink2, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false});
        C.candles = api.chart.addCandlestickSeries({...candleOptions()});
        api.chart.subscribeCrosshairMove((p) => drawCread(p && p.time != null ? Number(p.time) : null));
        return api;
      })
      .catch((e) => { C.loading = null; put(cslot, ui.errorBox(e)); return null; })
      .finally(() => { C.loading = null; });
    return C.loading;
  }
  function bandIndex() {
    const c = (st.d && st.d.chart) || {};
    if (c.symbol !== st.sym) return new Map();          // the answer of the coin before: never its band under these candles
    const band = c.band || {};
    const cells = band[HTF[st.tf]] || [];
    return new Map(cells.map((c) => [Number(c.t), c]));
  }
  async function drawChart() {
    const d = st.d;
    chartSub.textContent = `${fmt.coin(st.sym)} ${fmt.tfKo(st.tf)}봉 · 아래 띠 = 그 봉이 끝날 때 봇이 본 ${fmt.tfKo(HTF[st.tf])} 판단 · 한국 시간`;
    drawCoinNow();
    if (st.cErr && !st.c) { put(cslot, ui.errorBox(st.cErr, () => loadCandles(true))); return; }
    if (!st.c || st.c.key !== `${st.sym}|${st.tf}`) { put(cslot, h("div", {class: "ltc-cwait"}, "가격 봉을 불러오는 중")); return; }
    const rows = st.c.rows || [];
    if (!rows.length) { put(cslot, ui.empty("가격 봉이 없어요")); return; }
    const api = await ensureChart();
    if (!api || !ctx.alive()) return;
    put(cslot);
    const col = colors();
    const dec = priceDec(rows[rows.length - 1].close);
    const pf = {type: "price", precision: dec, minMove: Math.pow(10, -dec)};
    C.candles.applyOptions({priceFormat: pf});
    C.ema.applyOptions({priceFormat: pf});
    C.candles.setData(rows.map((r) => ({time: r.time, open: r.open, high: r.high, low: r.low, close: r.close})));
    const e = ema(rows.map((r) => r.close), 20);
    C.ema.setData(rows.map((r, i) => (e[i] == null ? {time: r.time} : {time: r.time, value: e[i]})));
    const byT = bandIndex();
    C.band.setData(rows.map((r) => {
      const b = bandBar(bandAt(byT, r.time, st.tf));
      return b ? {time: r.time, value: b.value, color: col[b.key]} : {time: r.time};
    }));
    const times = new Set(rows.map((r) => r.time));
    const c = (d && d.chart && d.chart.symbol === st.sym) ? d.chart : null;
    C.candles.setMarkers(c ? chartMarks(c, st.tf, times).map(({key, ord, ...m}) => ({...m, color: col[key]})) : []);
    for (const pl of C.lines) { try { C.candles.removePriceLine(pl); } catch (err) { /* gone */ } }
    C.lines = [];
    if (c) {
      for (const w of c.waits || []) {
        if (!ok(w.level)) continue;
        C.lines.push(C.candles.createPriceLine({price: Number(w.level), color: col.warn, lineWidth: 1, lineStyle: 2, axisLabelVisible: true,
          title: `되돌림 대기 ${SIDE(w.side)} ${fmt.tfKo(w.tf)}`}));
      }
      if (c.position && ok(c.position.entry_price)) {
        C.lines.push(C.candles.createPriceLine({price: Number(c.position.entry_price), color: col.muted, lineWidth: 1, lineStyle: 0,
          axisLabelVisible: true, title: `페이퍼 진입 ${SIDE(c.position.side)}`}));
      }
    }
    const key = `${st.sym}|${st.tf}`;
    if (st.fitKey !== key) {
      st.fitKey = key;
      // ~150 bars on a PC, fewer on a phone (a bar at least ~6 px wide, never under 40)
      const show = Math.max(40, Math.min(SHOW_BARS, Math.round((cbox.clientWidth || 900) / 6)));
      // room on the right for the newest markers' words
      api.chart.timeScale().setVisibleLogicalRange({from: Math.max(0, rows.length - show), to: rows.length + Math.max(3, Math.round(show / 15))});
    }
    drawCread(null);
  }
  function drawCoinNow() {
    const d = st.d;
    if (!d || d.state !== "ok") { put(coinNow); return; }
    const row = ((d.heat || {}).coins || {})[st.sym] || {}, now = Number(d.now_ms);
    put(coinNow, ["1h", "4h"].map((tf) => {
      const r = row[tf] || {};
      const c = (r.cells || []).find((x) => Number(x.t) <= now && now < Number(x.t) + TF_MS[tf]);
      const x = cellInfo(r.state === "ok" ? c : null, tf, rules());
      return h("span", {class: ["ltc-cn", ENTRY[tf] === st.tf ? "mine" : ""]}, h("span", {class: "ltc-cnk"}, `${fmt.tfKo(tf)} 지금`),
        h("b", {class: ["ltc-word", x.cls.split(" ")[0]]}, r.state === "pending" ? "불러오는 중" : x.word),
        h("span", {class: ["ltc-allow", x.allow.side > 0 ? "up" : x.allow.side < 0 ? "down" : ""]}, x.allow.ko));
    }));
  }
  /** The crosshair's bar in words (the newest bar without one). */
  function drawCread(time) {
    const rows = (st.c && st.c.rows) || [];
    if (!rows.length) { put(cread); return; }
    const r = rows.find((x) => x.time === time) || rows[rows.length - 1];
    const ms = TF_MS[st.tf];
    const b = bandAt(bandIndex(), r.time, st.tf);
    const x = cellInfo(b, HTF[st.tf], rules());
    const t = r.time * 1000;
    const c = st.d && st.d.chart && st.d.chart.symbol === st.sym ? st.d.chart : null;
    const sigs = c ? (c.signals || []).filter((s) => s.tf === st.tf && Number(s.t) === t + ms) : [];
    const forming = t + ms > Number((st.d && st.d.now_ms) || Date.now());
    put(cread,
      h("span", {class: "num ltc-ct"}, `${fmt.kst(t)} ${fmt.tfKo(st.tf)}봉${forming ? " (진행 중)" : ""}`),
      h("span", {class: "num"}, ` 종가 ${fmt.price(r.close)}`),
      h("span", null, ` · 끝날 때 본 ${fmt.tfKo(HTF[st.tf])} 판단 `),
      b ? h("b", {class: ["ltc-word", x.cls.split(" ")[0]]}, x.word)
        : h("b", {class: "ltc-word na"}, !c ? "불러오는 중" : forming ? "아직 안 끝남" : "기록 없음"),
      b ? h("span", {class: "ltc-allow"}, ` (${x.allow.ko})`) : null,
      sigs.length ? h("span", {class: "ltc-csig"}, ` · 신호 ${sigs.map((s) => `${fmt.stratKo(s.strategy)} ${SIDE(s.side)} ${s.kind_ko}`).join(", ")}`) : null);
  }
  function drawEvents() {
    const c = st.d && st.d.chart;
    if (!c || c.symbol !== st.sym) { put(events); return; }
    const items = [];
    for (const s of c.signals || []) {
      items.push({t: Number(s.t), node: h("li", {class: ["ltc-ev", "k-" + s.kind, s.before ? "before" : ""]},
        h("span", {class: "num ltc-et"}, fmt.kst(s.t)),
        h("span", {class: "ltc-ew"}, h("b", null, `${SIDE(s.side)} 신호`), ` ${fmt.stratKo(s.strategy)} ${fmt.tfKo(s.tf)}`),
        ui.pill(s.kind_ko, s.kind === "entered" ? "good" : s.kind === "wait" ? "warn" : "thin",
          s.before ? "추세판단 봇이 켜지기 전, 예전 봇의 신호예요 (이 봇의 판단이 아님)" : null),
        s.why ? h("small", {class: "ltc-esub"}, s.why) : null)});
    }
    for (const x of c.trades || []) {
      items.push({t: Number(x.exit_time), node: h("li", {class: ["ltc-ev", "k-trade", x.before ? "before" : ""]},
        h("span", {class: "num ltc-et"}, fmt.kst(x.exit_time)),
        h("span", {class: "ltc-ew"}, h("b", null, `${x.before ? "전환 전 " : ""}${SIDE(x.side)} 거래 청산`),
          ` ${fmt.stratKo(x.strategy)} ${fmt.tfKo(x.tf)} · 진입 ${fmt.kst(x.entry_time)}${x.before ? " · 예전 봇이 연 것" : ""}`),
        ui.pill(exitKo(x.reason), x.reason === "LOCK" ? "good" : x.reason === "SL" || x.reason === "LIQ" ? "bad" : "accent"),
        h("b", {class: ["num", fmt.tone(x.roe)]}, fmt.pct(x.roe, 1)),
        x.why || x.entry_judge ? h("small", {class: "ltc-esub"}, [x.why, x.entry_judge ? `진입 때 ${x.entry_judge}` : null].filter(Boolean).join(" · ")) : null)});
    }
    if (c.position) {
      const p = c.position;
      items.push({t: Number(p.entry_time), node: h("li", {class: "ltc-ev k-open"}, h("span", {class: "num ltc-et"}, fmt.kst(p.entry_time)),
        h("span", {class: "ltc-ew"}, h("b", null, `${SIDE(p.side)} 보유 중`), ` ${fmt.stratKo(p.strategy)} ${fmt.tfKo(p.tf)} · 진입 ${fmt.price(p.entry_price)}`),
        ui.pill(p.before ? "전환 전 포지션" : "페이퍼 포지션", p.before ? "warn" : "accent",
          p.before ? "예전 봇이 연 포지션이에요 · 새 봇이 이어서 정리해요 (새 봇 성적엔 안 셈)" : null),
        p.entry_judge ? h("small", {class: "ltc-esub"}, `진입 때 ${p.entry_judge}`) : null)});
    }
    for (const w of c.waits || []) {
      items.push({t: Number(w.t0) || 0, node: h("li", {class: "ltc-ev k-wait"}, h("span", {class: "num ltc-et"}, fmt.kst(w.t0)),
        h("span", {class: "ltc-ew"}, h("b", null, `${SIDE(w.side)} 되돌림 대기`), ` ${fmt.stratKo(String(w.member || "").split("@")[0])} ${fmt.tfKo(w.tf)} · `,
          h("span", {class: "num"}, fmt.price(w.level)), ` 닿으면 진입 · ${fmt.hm(w.until)}까지`),
        ui.pill("지금 기다림", "warn"), w.judge ? h("small", {class: "ltc-esub"}, w.judge) : null)});
    }
    items.sort((a, b) => b.t - a.t);
    const first = items.slice(0, 10).map((x) => x.node), rest = items.slice(10).map((x) => x.node);
    put(events, items.length ? [h("ul", {class: "ltc-evlist"}, first),
      rest.length ? ui.disclosure(`${fmt.int(rest.length)}개 더 보기`, h("ul", {class: "ltc-evlist"}, rest)) : null]
      : ui.empty(`${fmt.coin(st.sym)}: 최근 3일 신호·거래가 없어요`));
  }

  // ---------------------------------------------------------------- the legend and 읽는 법
  function heatLegend() {
    const sw = (cls, ko) => h("li", null, h("i", {class: ["ltc-sw", cls], "aria-hidden": "true"}), ko);
    return h("ul", {class: "ltc-legend", "aria-label": "색 설명"},
      sw("up", "상승 (그 방향 진입 받음)"), sw("down", "하락"), sw("hold up", "보류 · 3/4는 나왔지만 유지 확인 중"), sw("hold", "보류"),
      sw("up weak", "힘 약함 · 끝물 (진입 안 함)"), sw("na", "못 읽음"),
      h("li", null, h("i", {class: "ltc-sw dot", "aria-hidden": "true"}), "페이퍼 롱 진입"),
      h("li", null, h("i", {class: "ltc-sw dot short", "aria-hidden": "true"}), "숏 진입"),
      h("li", null, h("i", {class: "ltc-sw xx", "aria-hidden": "true"}, "×"), "감독 청산"),
      h("li", null, h("i", {class: "ltc-sw start", "aria-hidden": "true"}), "새 봇 시작 (왼쪽 흐린 점 = 전환 전 예전 봇)"));
  }
  function chartLegend() {
    const sw = (cls, ko, txt) => h("li", null, h("i", {class: ["ltc-mk", cls], "aria-hidden": "true"}, txt || null), ko);
    return h("ul", {class: "ltc-legend ltc-clegend", "aria-label": "차트 표시 설명"},
      sw("in", "진입한 신호"), sw("wait", "되돌림 기다림"), sw("miss", "되돌림 안 옴"), sw("blk", "추세 판단·진입 자리에 걸림", "×"),
      sw("arr", "페이퍼 진입 ▲▼"), sw("ex", "청산 (이유를 글로)"), sw("dash", "되돌림 대기 가격"), sw("ema", "EMA20"),
      sw("band", "아래 띠: 높으면 진입 받는 추세, 낮으면 진입 안 함"));
  }
  function howTo() {
    return h("ul", {class: "ltc-how"},
      h("li", null, "칸 하나 = 끝난 봉 하나의 판단이 쓰인 시간이에요. 14:00에 끝난 1시간봉 판단은 14:00~15:00 칸, 4시간 줄은 칸이 4시간."),
      h("li", null, "30분 진입은 1시간 줄, 1시간 진입은 4시간 줄을 봐요. 진입 점은 그 진입이 본 줄에 찍혀요."),
      h("li", null, "판단 4개(V3.9 · EMA·DMI·ADX · OBV · 일목·AO) 중 3개 이상 같은 쪽이면 상승/하락. 1시간은 끝난 봉 2개 연속, 4시간은 1개여야 해요 (아니면 연한 색 = 유지 확인 중)."),
      h("li", null, "ADX 20 미만은 힘 약함, 40 넘고 꺾이면 끝물: 색은 남지만 빗금이고 진입은 안 해요."),
      h("li", null, "차트 아래 띠는 그 봉이 끝날 때 봇이 본 상위 봉 판단이에요. 신호는 그 봉에, 거래는 진입·청산한 봉에 찍혀요."),
      h("li", {class: "ltc-sub"}, "봇은 끝난 봉 300개로 판단하고, 이 화면은 같은 함수로 더 긴 기록(최대 499개)에서 봉마다 다시 계산해요. 지금 칸은 봇이 남긴 판단과 맞춰 보고, 다르면 위에 '봇 기록과 다름'이라고 써요."));
  }

  // ---------------------------------------------------------------- picks and loads
  function pick(sym, tf) {
    let changed = false;
    if (sym && COINS.includes(sym) && sym !== st.sym) { st.sym = sym; local.set("ltc-sym", sym); coinSeg.set(sym); changed = true; }
    if (tf && HTF[tf] && tf !== st.tf) { st.tf = tf; local.set("ltc-tf", tf); tfSeg.set(tf); changed = true; }
    if (st.d && st.d.state === "ok") { drawHeat(); drawCoinNow(); }
    if (!changed) return;
    drawChart();
    drawEvents();
    loadCandles(true).catch(() => {});
    load().catch(() => {});
  }
  function pickTf(tf) { pick(null, tf); }
  async function loadCandles(force) {
    const key = `${st.sym}|${st.tf}`;
    if (!force && st.cBusy) return;
    st.cBusy = true;
    let rows;
    try { rows = await ctx.api(`${CANDLES}?symbol=${st.sym}&interval=${st.tf}&limit=${FETCH_BARS}`); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      st.cErr = e;
      if (key === `${st.sym}|${st.tf}`) { if (st.c && st.c.key === key) put(cslot, ui.staleNote(e, st.cAt)); else { st.c = null; drawChart(); } }
      return;
    } finally { st.cBusy = false; }
    if (!ctx.alive() || key !== `${st.sym}|${st.tf}`) return;
    st.cErr = null; st.c = {key, rows: Array.isArray(rows) ? rows : []}; st.cAt = Date.now();
    drawChart();
  }
  function quickAgain() {
    if (st.quick) return;
    st.quick = setTimeout(() => { st.quick = null; if (ctx.alive()) load().catch(() => {}); }, QUICK_MS);
  }
  function draw() {
    const d = st.d;
    if (!d || d.state !== "ok") {
      cards.hidden = true;
      put(stateSlot, d && d.state === "off" ? h("div", {class: "lb-state"}, ui.pill("꺼짐", "thin"), h("span", null, ` ${d.reason_ko}`))
        : sourceState(d, "추세판단 봇"));
      return;
    }
    cards.hidden = false;
    put(stateSlot, d.rules && d.rules.from !== "bot" ? h("div", {class: "lb-state"}, ui.pill("기본값", "warn"),
      h("span", null, d.rules.from === "config" ? " 봇이 쓴 숫자 기록이 없어 설정 파일의 추세 숫자로 계산했어요" : " 봇 설정에서 숫자를 못 읽어 기본 숫자로 계산했어요")) : null);
    drawHeat();
    drawChart();
    drawEvents();
    if (d.pending) quickAgain();
  }
  async function load() {
    if (st.busy) return;
    st.busy = true;
    const sym = st.sym;
    let d;
    try { d = await ctx.api(`${API}?symbol=${sym}`); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (st.d) { put(stateSlot, ui.staleNote(e, st.okAt, () => load().catch(() => {}))); ui.dim(main, true); }
      else put(stateSlot, ui.errorBox(e, () => load()));
      throw e;
    } finally { st.busy = false; }
    if (!ctx.alive()) return;
    if (sym !== st.sym) { load().catch(() => {}); return; }
    ui.dim(main, false);
    st.d = d; st.okAt = Date.now();
    const pinned = st.pin && ((((d.heat || {}).coins || {})[st.pin.sym] || {})[st.pin.tf] || {}).cells;
    if (st.pin && !(pinned || []).some((x) => Number(x.t) === st.pin.t)) st.pin = null;
    draw();
  }
  if (ctx.track) ctx.track(() => { if (st.quick) clearTimeout(st.quick); });
  load().catch(() => {});
  loadCandles(true).catch(() => {});
  ctx.every(REFRESH_MS, () => { load().catch(() => {}); loadCandles(false).catch(() => {}); }, {now: false});
  if (ctx.watch) ctx.watch("board", () => { if (st.d && st.d.state === "ok") { drawHeat(); drawEvents(); drawCread(null); } });
  return {el, set() {}};
}

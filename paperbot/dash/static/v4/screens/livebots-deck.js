// 실거래 › 관제실 (#/deck; owners 2026-11-01: "이런 화면느낌으로 메인화면으로 똑같이 만들어 줄수 있어?" with three pictures of
// trading-terminal dashboards): the site's main screen. One answer (dash/more/livedeck.py, /api/v4/livebots/deck, every 15 s)
// for every panel, read-only:
//   top      the name, each coin's last 15m close and its 24-hour change, the clock (KST · UTC); a running line of the
//            bots' newest log rows
//   지갑      the three bots' balance together, against their start, today's and all closed trades
//   차트      the chosen coin's last 120 15m bars, the 3합 histogram's 0 crosses on them (▲▼: the 친구 15분 봇's entry,
//            owners 11-02), the OBV4 MACD histogram's turns that are the 레인지 봇's entry (○, owners 11-03; the 바이비트
//            봇's on 11-02), the 30m 추세 MACD's side of 0 as a strip under them (the bots' trend), a bot's entry and stop
//   봇        each bot: running or not, its rules, balance, record, position, live vs paper
//   추세 그리드 coin x bot: the trend each bot read at its last close (초록 상승 · 빨강 하락) and its signal
//   목표 ×6   this month against the path to the owners' ×6 (the three bots together and each), the daily growth the rest
//            needs, each bot's own pace (가상) and the 목표 연구's verdict, a link to it
//   포지션 진행 each bot's lane from its stop through the entry to the ladder's next lock, the price now
//   코어      the six coins' 24-hour lines beside an attractor drawn in the owners' picture's colours: a fan of lines per coin
//            in its 30m 추세 MACD colour, the coin whose histogram crossed 0 at the last 15m close white, the held coin amber
//            and pulsing, a fan per recent close to the late fills; three probes with real values
//   실행 기록  the three logs' newest rows (signals, entries, ladder steps, exits, skips)
//   포워드 테스트 each bot's balance line from its start, split where it began the 10-31 night rules (이전 규칙 · 새 규칙),
//            the return and the deepest drop since, live vs paper entries
//   히스토그램 the chosen coin's entry histogram on its 15m bars (the answer's hist_rule: the 3합, or the OBV histogram
//            once both bots enter on its turn, owners 11-03 last "친구봇도 obv로"); 신호 흐름: the last 48 hours' signals (0 crosses, OBV
//            histogram turns) and entries by 15m
// HONESTY: every number is a bot's record or a price; a panel with nothing yet says so; nothing drawn is made up (the core's
// flow shape, its stars and its particle colours are decoration and say so on the screen, never a model). Under reduced
// motion the core and the running lines stand still.
import {h, s, put, ui, fmt, motion, serverNow, sound} from "../core/pb.js";

export const DECK_API = "/api/v4/livebots/deck";
const REFRESH_MS = 15 * 1000;
const MIN = 60 * 1000;
const MIN15 = 15 * MIN;
const FRAME_MS = 33;
const ok = (x) => x != null && x !== "" && Number.isFinite(Number(x));
const TONE = {1: "up", "-1": "down", 0: "flat"};
export const toneOf = (t) => (ok(t) ? TONE[Number(t)] || "flat" : "na");
const TREND_KO = {up: "상승", down: "하락", flat: "진입 금지", na: "—"};
// owners 11-02: the bots' trend is the 30m 추세 MACD histogram's side of 0 (its yellow bars too); the 친구 15분 봇 enters on
// the 15m 3합 histogram's 0 cross, the 레인지 봇 on the OBV4 MACD histogram's turn (owners 11-03; the 바이비트 봇, which
// had that rule on 11-02, is off: the screen shows the bots livedeck.bot_order() reads)
const TM_KO = "추세 MACD";
/** The coin's entry histogram in words (livedeck hist_rule): the OBV histogram once every live bot enters on its turn. */
export const histKo = (c) => ((c || {}).hist_rule === "o4h" ? "OBV 히스토그램" : "3합 히스토그램");
/** The entry mark on a bar in words: the OBV turn (0선 아래 양봉 / 0선 위 음봉) or the 3합's 0 cross; "" without one. */
export const markKo = (c, x) => (!Number(x) ? "" : (c || {}).hist_rule === "o4h" ? (x > 0 ? "0선 아래 양봉 전환" : "0선 위 음봉 전환")
  : (x > 0 ? "0선 위로 돌파" : "0선 아래로 돌파"));
const BOT_TAB = {bybit: "bybitbot", mix: "mixbot", range: "rangebot"};   // each bot's 봇별 screen (its 목표 연구 at the foot)
/** Each coin's own colour (dk-k0 … dk-k5, in the server's fixed coin order; never a colour that means up or down). */
const CID = (k) => `dk-k${k % 6}`;
/** The goals the owners named (11-01: "100달러로 한달만에 700달러, 800달러 … 5000달러 그이상"), ×6 the one they keep. */
export const GOAL_LADDER = [6, 7, 10, 20, 50];
/** The price now (owners 11-01 "다 해줘"): dash/more/livedeck.py px_view, Binance futures' mark price, last trade and
 *  funding, one fetch per 5 s shared by every viewer; read every PX_MS, older than PX_FRESH_MS is not "now" any more. */
export const PX_API = "/api/v4/livebots/deck/px";
const PX_MS = 5 * 1000;
const PX_FRESH_MS = 30 * 1000;

// ---------------------------------------------------------------- pure (node tests: tests/test_dash_livedeck.py)
/** A coin's price now: the live mark (else the last trade) while fresh, src "live"; else its last closed 15m bar, src
 *  "15m"; null when neither is known. Also the coin's funding rate and next funding time when live. */
export function priceNow(live, liveAt, coin, nowMs) {
  const r = live && live.coins && coin && !Array.isArray(live.coins) ? live.coins[coin.symbol] : null;
  if (r && ok(liveAt) && nowMs - liveAt <= PX_FRESH_MS && (ok(r.mark) || ok(r.last))) {
    return {px: Number(ok(r.mark) ? r.mark : r.last), src: "live", funding: ok(r.funding) ? Number(r.funding) : null,
      next_ms: ok(r.next_ms) ? Number(r.next_ms) : null};
  }
  return coin && coin.state === "ok" && ok(coin.last) ? {px: Number(coin.last), src: "15m", funding: null, next_ms: null} : null;
}
/** 위험 한눈에 for one open position at price `px` (owners 11-01): pnl ($) and roe (of the margin) now, before fees; the
 *  liquidation price (isolated: entry × (1 − side × (1/lev − mmr)), the card's rough figure) and how far the price is from
 *  it and from the stop (fractions of the price, > 0 = room left); the P&L if the stop is hit (the bot's own stop_pnl,
 *  before fees) and that as a share of the bot's balance; the funding (rate; pays: this side pays it; usd: one funding on
 *  the notional now, < 0 = paid). Null without a position or a price. */
export function riskOf(pos, px, equity, mmr = 0.005, funding = null) {
  if (!pos || pos.state !== "ok" || !ok(pos.entry) || !ok(px)) return null;
  const side = Number(pos.side), e = Number(pos.entry), p = Number(px), lev = Number(pos.leverage) || null;
  const q = ok(pos.qty) ? Number(pos.qty) : null;
  const liq = lev ? e * (1 - side * (1 / lev - Number(mmr))) : null;
  const stopPnl = ok(pos.stop_pnl) ? Number(pos.stop_pnl) : ok(pos.stop) && q ? side * (Number(pos.stop) - e) * q : null;
  const eq = ok(equity) ? Number(equity) : ok(pos.equity_before) ? Number(pos.equity_before) : null;
  const notional = q ? q * p : null;
  return {px: p, pnl: q ? side * (p - e) * q : null, roe: lev ? side * (p / e - 1) * lev : null, liq,
    toLiq: ok(liq) ? side * (p - liq) / p : null, toStop: ok(pos.stop) ? side * (p - Number(pos.stop)) / p : null,
    stopPnl, stopPct: ok(stopPnl) && eq ? stopPnl / eq : null,
    funding: ok(funding) ? {rate: Number(funding), pays: side * Number(funding) > 0, usd: notional ? -side * Number(funding) * notional : null} : null};
}
/** The risk bar of one position: where the liquidation, the stop, the entry and the price now sit on a line from the
 *  liquidation (0) to as far past the entry on the other side (1), each 0…1 (clamped), null when unknown. */
export function riskBar(pos, r) {
  if (!r || !ok(r.liq) || !ok(pos.entry)) return null;
  const side = Number(pos.side), e = Number(pos.entry), w = 2 * Math.abs(e - r.liq) || 1;
  const at = (x) => (ok(x) ? Math.max(0, Math.min(1, side * (Number(x) - r.liq) / w)) : null);
  return {liq: 0, stop: at(pos.stop), entry: at(e), now: at(r.px)};
}
/** "+$1.23" / "−$4.50" (fmt.usd with the sign); "—" when unknown. */
export const usdKo = (x) => (ok(x) ? `${Number(x) >= 0 ? "+" : "−"}${fmt.usd(Math.abs(Number(x)))}` : "—");
/** The sounds of the bots' new records (core/sound.js playLive: the site's sound switch, its events and quiet hours):
 *  an entry, an exit with a gain, an exit with a loss (or a P&L not read). */
export function liveSoundsOf(rows) {
  const out = [];
  for (const r of rows || []) {
    const k = r.kind === "entry" || r.kind === "adopted" ? "lv_entry" : r.kind === "exit" ? (ok(r.pnl) && Number(r.pnl) > 0 ? "lv_tp" : "lv_sl") : null;
    if (k && !out.includes(k)) out.push(k);
  }
  return out;
}
/** 목표별 하루 필요: for each multiple over n days from `start` dollars, the end in dollars and the daily rate compounding
 *  needs (x^(1/n) − 1). Arithmetic only, never a forecast. */
export function ladderOf(xs = GOAL_LADDER, n = 30, start = 100) {
  return (xs || []).filter((x) => ok(x) && Number(x) > 0)
    .map((x) => ({x: Number(x), usd: start * Number(x), daily: Math.pow(Number(x), 1 / Math.max(1, Number(n) || 30)) - 1}));
}
/** 코인 흐름: each coin's last 96 15m closes as a ratio to the first one, in the coins' order (k = its colour). */
export function feedLines(coins) {
  return (coins || []).map((c, k) => {
    const v = (c && c.state === "ok" ? c.spark || [] : []).filter(ok).map(Number);
    if (v.length < 2 || !(v[0] > 0)) return null;
    return {k, coin: c.coin, pts: v.map((x, i) => [i, x / v[0] - 1]), last: v[v.length - 1] / v[0] - 1};
  }).filter(Boolean);
}
/** The wire (the pictures' raw message log): the newest bot records, each one line as the record has it. */
export function wireOf(tape, n = 7) {
  return (tape || []).slice(0, n).map((r) => ({t: ok(r.ts) ? fmt.hm(r.ts) : "--:--", kind: r.kind || "",
    txt: JSON.stringify({bot: r.bot_ko, coin: r.coin || "—", kind: r.kind, side: r.side || 0, ...(ok(r.pnl) ? {pnl: Math.round(Number(r.pnl) * 100) / 100} : {}), text: r.text})}));
}
/** "+1.23%" / "−0.40%" of a ratio; "—" when unknown. */
export const pctKo = (r, dec = 2) => (ok(r) ? `${Number(r) > 0 ? "+" : ""}${fmt.num(Number(r) * 100, dec)}%` : "—");
/** A price with its own digits (6 significant, no trailing zeros). */
export const pxKo = (x) => (ok(x) ? String(Number(Number(x).toPrecision(6))) : "—");
/** The next 15m close after ``now`` and how far it is: {at, left_ms}. */
export function nextClose(now) {
  const at = Math.floor(now / MIN15) * MIN15 + MIN15;
  return {at, left_ms: at - now};
}
/** "mm:ss" of ms. */
export const mmss = (ms) => {
  const t = Math.max(0, Math.round(ms / 1000));
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
};
/** A coin's 30m 추세 MACD now in words (owners 11-02): "상승 +3.21" / "하락 −1.40" / "0선". */
export function tmKo(c) {
  const tr = c && c.trend30 && c.trend30.length ? toneOf(c.trend30[c.trend30.length - 1][1]) : "na", t = (c && c.tm30) || {};
  return `${tr === "flat" ? "0선" : TREND_KO[tr]}${ok(t.hist) ? ` ${fmt.num(t.hist, 2, true)}` : ""}`;
}
/** A grid cell of one coin and one bot: {tone, big, sub, sig} from the bot's board row (livedeck.grid_view). */
export function cellOf(c) {
  if (!c) return {tone: "na", big: "—", sub: "기록 없음", sig: 0};
  const tone = toneOf(c.trend);
  const big = c.rule === "o4h" ? (ok(c.o4) ? `OBV ${fmt.num(c.o4, 1)}` : "OBV —") : c.rule === "h3x" ? (ok(c.h3) ? fmt.num(c.h3, 1) : "—")
    : c.rule === "obvac" ? (ok(c.ac) ? `AC ${fmt.num(c.ac, 2)}` : "AC —") : ok(c.h6) ? fmt.num(c.h6, 1) : "—";
  const sig = Number(c.side) || 0;
  const what = c.rule === "o4h" ? (c.o4_turn ? (c.o4_turn > 0 ? "양봉 전환" : "음봉 전환") : "")
    : c.rule === "obvac" ? (c.turn ? (c.turn > 0 ? "OBV 진한 초록" : "OBV 진한 빨강") : "") : c.x0 ? (c.x0 > 0 ? "0선 ↑" : "0선 ↓") : "";
  const sub = sig ? `${sig > 0 ? "롱" : "숏"} 신호` : what ? `${what} · ${TREND_KO[tone]}` : TREND_KO[tone];
  return {tone, big, sub, sig};
}
/** A bot's lane (포지션 진행): the stop, the entry, the next lock and the price now on one 0..1 line. */
export function laneOf(pos, price) {
  if (!pos || pos.state !== "ok" || !ok(pos.entry) || !ok(pos.stop)) return null;
  const nx = pos.next && ok(pos.next.trigger) ? Number(pos.next.trigger) : ok(pos.first_act_price) ? Number(pos.first_act_price) : null;
  const pts = [Number(pos.stop), Number(pos.entry), nx, ok(price) ? Number(price) : null].filter((x) => x != null);
  const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo || Math.abs(Number(pos.entry)) * 0.01 || 1;
  const at = (x) => (x == null ? null : (Number(x) - lo) / span);
  const flip = Number(pos.side) < 0;                 // a short reads right to left: the stop always on the left
  const f = (x) => (x == null ? null : flip ? 1 - x : x);
  return {stop: f(at(pos.stop)), entry: f(at(pos.entry)), next: f(at(nx)), now: f(at(price)), nextPx: nx,
    roe: ok(price) && Number(pos.leverage) ? Number(pos.side) * (Number(price) - Number(pos.entry)) / Number(pos.entry) * Number(pos.leverage) : null};
}
/** A balance line as % of its first point: [[ms, ratio], …]. */
export function pctCurve(curve) {
  const c = (curve || []).filter((p) => ok(p[0]) && ok(p[1]));
  if (!c.length || !Number(c[0][1])) return [];
  return c.map((p) => [Number(p[0]), Number(p[1]) / Number(c[0][1]) - 1]);
}
/** Since ``t0`` on a % line: {ret, dd} (the return and the deepest drop from a high), null without points after it. */
export function since(curve, t0) {
  const c = pctCurve(curve);
  if (!c.length) return null;
  const k = ok(t0) ? c.findIndex((p) => p[0] >= Number(t0)) : 0;
  if (k < 0) return null;
  const base = k > 0 ? c[k - 1] : c[0];
  const pts = [base, ...c.slice(k)].map((p) => 1 + p[1]);
  let hi = pts[0], dd = 0;
  for (const v of pts) { hi = Math.max(hi, v); dd = Math.min(dd, v / hi - 1); }
  return {ret: pts[pts.length - 1] / pts[0] - 1, dd};
}

// ---------------------------------------------------------------- 목표 ×6 (owners 11-01: "내 1달 목표 수익률 달성을 위해 필요한
// 대시보드 화면 내용들 있으면 추가해도 돼"): the bots' month against the path to ×6, the 목표 연구 arithmetic (livegoalres)
/** The ×target path's multiple on day ``d`` of an ``n``-day month (the 목표 연구's path: target^(d / n)). */
export const pathAt = (target, d, n = 30) => (ok(target) && Number(target) > 0 && ok(d) ? Math.pow(Number(target), Math.max(0, Number(d)) / n) : null);
/** "×1.23" of a multiple ("×1000 넘게" / "×0.01 아래" past those); "—" when unknown. */
export const multKo = (m, dec = 2) => (!ok(m) ? "—" : Number(m) > 1000 ? "×1000 넘게" : Number(m) < 0.01 ? "×0.01 아래" : `×${fmt.num(Number(m), dec)}`);
/** "55%" of a rate; "—" when unknown. */
export const rateKo = (r) => (ok(r) ? `${fmt.num(Number(r) * 100, 0)}%` : "—");
/** A bot's line this month in multiples of its month-start balance: [[day, multiple], …] from its balance curve (the
 * equity after each exit) and its balance now; [] without this month's numbers. */
export function monthLine(curve, month, nowMs) {
  if (!month || !ok(month.start_equity) || !Number(month.start_equity) || !ok(month.from_ms)) return [];
  const f = Number(month.from_ms), e0 = Number(month.start_equity), day = (t) => (t - f) / 86400000;
  const pts = [[0, 1]];
  for (const p of curve || []) if (ok(p[0]) && ok(p[1]) && Number(p[0]) > f) pts.push([day(Number(p[0])), Number(p[1]) / e0]);
  if (ok(month.now_equity) && ok(nowMs) && Number(nowMs) > f) pts.push([day(Number(nowMs)), Number(month.now_equity) / e0]);
  return pts.sort((a, b) => a[0] - b[0]);
}

/** The signal an entry was made on, in the owners' words (the entry row's ``why``). */
export function whyKo(w) {
  if (!w) return "";
  const tr = toneOf(w.trend);
  const bar = (w.trend_mode === "macd" ? `${TM_KO} ${w.trend_tf || w.tf || ""} ${tr === "flat" ? "0선" : TREND_KO[tr]}${ok(w.tmacd) ? ` (${fmt.num(w.tmacd, 2)})` : ""}`
    : `추세 바 ${w.trend_tf || w.tf || ""} 종합 ${TREND_KO[tr]}`).replace(/\s+/g, " ");
  if (w.rule === "h3x") return `${w.tf || ""}봉 3합 히스토그램 0선 ${Number(w.x0) > 0 ? "위로" : "아래로"} 돌파${ok(w.h3) ? ` (${fmt.num(w.h3, 2)})` : ""} · ${bar}`;
  if (w.rule === "o4h") return `${w.tf || ""}봉 OBV 히스토그램 ${Number(w.o4_turn) > 0 ? "0선 아래 양봉 전환" : "0선 위 음봉 전환"}${ok(w.o4) ? ` (${fmt.num(w.o4, 2)})` : ""} · ${bar}`;
  if (w.rule === "h0x") return `${w.tf || ""}봉 히스토그램 0선 ${Number(w.x0) > 0 ? "위로" : "아래로"} 돌파${ok(w.h6) ? ` (${fmt.num(w.h6, 2)})` : ""} · ${bar}`;
  if (w.rule === "obvac") {
    const ac = ok(w.ac) ? `${Number(w.ac) > 0 ? "플러스" : "마이너스"} ${Number(w.ac_col) > 0 ? "양봉" : "음봉"} (${fmt.num(w.ac, 2)})` : "—";
    return `${w.tf || ""}봉 OBV ${Number(w.turn) > 0 ? "연한→진한 초록" : "연한→진한 빨강"} · AC ${ac} · ${bar}`;
  }
  return bar;
}
/**
 * 진입 카드 (owners 11-01, their picture of an entry card): the open position of a bot (else the newest entry of any bot,
 * said to be past): side, coin, bot, leverage; the trend bar's rows on its side at the signal (n / 6: the bots compute no
 * "confidence", this is what they read); 진입 (price, the signal), 손절 (price, distance, ATR x k), 목표 (the ladder: its
 * first lock and steps); 손익비 (the first lock's distance : the stop's), the leverage, the liquidation price (about: the
 * leverage and the maintenance margin the bots' guard uses). null when no bot ever entered.
 */
export function cardOf(bots, mmr = 0.005) {
  const live = (bots || []).find((b) => b.position && b.position.state === "ok");
  let b = live, e;
  if (live) {
    const p = live.position, le = live.last_entry && live.last_entry.symbol === p.symbol ? live.last_entry : null;
    e = {symbol: p.symbol, coin: p.coin, side: Number(p.side), entry: p.entry, stop: p.stop, leverage: p.leverage, ts: p.opened_ms,
      why: (le && le.why) || {}, act: p.first_act_price, step: p.step || 0};
  } else {
    const all = (bots || []).filter((x) => x.last_entry && ok(x.last_entry.entry)).sort((a, c) => (c.last_entry.ts || 0) - (a.last_entry.ts || 0));
    if (!all.length) return null;
    b = all[0];
    const le = b.last_entry, lad = b.ladder;
    const act = lad && ok(le.leverage) ? Number(le.entry) * (1 + Number(le.side) * Number(lad.trigger) / 100 / Number(le.leverage)) : null;
    e = {...le, side: Number(le.side), act, step: 0};
  }
  const lev = Number(e.leverage) || null, side = e.side;
  const n = (e.why && e.why.bar_n) || null;
  const agree = n ? (side > 0 ? Number(n[0]) : Number(n[1])) : null;
  const tm = e.why && e.why.trend_mode === "macd" ? (ok(e.why.tmacd) ? Number(e.why.tmacd) : null) : undefined;   // (11-02)
  const dist = ok(e.entry) && ok(e.stop) ? Math.abs(Number(e.entry) - Number(e.stop)) / Number(e.entry) : null;
  const reward = ok(e.act) && ok(e.entry) ? Math.abs(Number(e.act) - Number(e.entry)) : null;
  const risk = ok(e.entry) && ok(e.stop) ? Math.abs(Number(e.entry) - Number(e.stop)) : null;
  const liq = ok(e.entry) && lev ? Number(e.entry) * (1 - side * (1 / lev - Number(mmr))) : null;
  const lad = b.ladder;
  return {live: !!live, bot: b.name_ko, coin: e.coin, symbol: e.symbol, side, sideKo: side > 0 ? "롱" : "숏", sideEn: side > 0 ? "LONG" : "SHORT",
    lev, ts: e.ts, agree, tm, entry: e.entry, stop: e.stop, act: e.act, step: e.step, why: whyKo(e.why), dist, stopAtr: b.stop_atr,
    rr: reward && risk ? reward / risk : null, liq,
    target: lad ? `${lad.basis === "gross" ? "거래소 ROE" : "순ROE"} +${fmt.num(lad.trigger, 0)}%에 닿으면 손절을 +${fmt.num(lad.lock, 0)}%로 옮기고, 그 뒤 ${fmt.num(lad.step, 0)}%마다 한 계단씩 올려요` : "계단 설정을 못 읽었어요"};
}

// ---------------------------------------------------------------- drawing helpers (SVG, colours from the css classes)
const VB = (w, hh) => `0 0 ${w} ${hh}`;
function sparkPath(vals, w, hh, pad = 2) {
  const v = (vals || []).filter(ok).map(Number);
  if (v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v), sp = hi - lo || 1;
  return v.map((x, i) => `${i ? "L" : "M"}${(pad + (i / (v.length - 1)) * (w - 2 * pad)).toFixed(1)},${(pad + (1 - (x - lo) / sp) * (hh - 2 * pad)).toFixed(1)}`).join("");
}
function spark(vals, cls, w = 120, hh = 32) {
  const d = sparkPath(vals, w, hh);
  return s("svg", {class: ["dk-spark", cls], viewBox: VB(w, hh), preserveAspectRatio: "none", "aria-hidden": "true"},
    d ? [s("path", {class: "dk-spark-a", d: `${d}L${w - 2},${hh}L2,${hh}Z`}), s("path", {class: "dk-spark-l", d})] : null);
}

/** The chosen coin's 15m candles, its 3합 0 crosses and OBV histogram turns, the 30m 추세 MACD strip, a bot's entry / stop. */
function chartSvg(c, holds, W = 600) {
  const H = 250, top = 8, bot = 196, strip = 214;
  const bars = c.bars || [];
  if (bars.length < 2) return ui.empty("봉이 없어요");
  const hs = holds.flatMap((p) => [p.entry, p.stop]).filter(ok).map(Number);
  const lo = Math.min(...bars.map((b) => b[3]), ...hs), hi = Math.max(...bars.map((b) => b[2]), ...hs);
  const sp = hi - lo || 1, n = bars.length, bw = W / n;
  const y = (v) => top + (1 - (v - lo) / sp) * (bot - top);
  const kids = [];
  for (let g = 0; g <= 4; g++) {
    const v = lo + (sp * g) / 4;
    kids.push(s("line", {class: "dk-gridl", x1: 0, x2: W, y1: y(v), y2: y(v)}), s("text", {class: "dk-axis", x: W - 2, y: y(v) - 2, "text-anchor": "end"}, pxKo(v)));
  }
  bars.forEach((b, i) => {
    const up = b[4] >= b[1], x = i * bw + bw / 2;
    kids.push(s("line", {class: ["dk-wick", up ? "up" : "down"], x1: x, x2: x, y1: y(b[2]), y2: y(b[3])}),
      s("rect", {class: ["dk-body", up ? "up" : "down"], x: x - bw * 0.35, width: Math.max(1, bw * 0.7), y: Math.min(y(b[1]), y(b[4])),
        height: Math.max(1, Math.abs(y(b[1]) - y(b[4])))}));
    const x0 = (c.cross || [])[i];
    if (x0) kids.push(s("path", {class: ["dk-x0", x0 > 0 ? "up" : "down"], d: x0 > 0 ? `M${x},${y(b[3]) + 10}l-4,6h8z` : `M${x},${y(b[2]) - 10}l-4,-6h8z`}));
    const o4 = c.hist_rule === "o4h" ? 0 : (c.o4side || [])[i];   // the OBV turn as a ring (no ring when ▲▼ are the OBV turns)
    if (o4) kids.push(s("circle", {class: ["dk-o4", o4 > 0 ? "up" : "down"], cx: x, cy: o4 > 0 ? y(b[3]) + 22 : y(b[2]) - 22, r: 3.2}));
  });
  const lastC = bars[n - 1][4];                       // the last close: a dashed line and its tag (the pictures' price tag)
  kids.push(s("line", {class: "dk-last", x1: 0, x2: W, y1: y(lastC), y2: y(lastC)}),
    s("rect", {class: "dk-lastbox", x: W - 64, y: y(lastC) - 8, width: 64, height: 16, rx: 1}),
    s("text", {class: "dk-lastt", x: W - 4, y: y(lastC) + 4, "text-anchor": "end"}, pxKo(lastC)),
    s("circle", {class: "dk-nowr", cx: (n - 1) * bw + bw / 2, cy: y(lastC), r: 4}), s("circle", {class: "dk-nowd", cx: (n - 1) * bw + bw / 2, cy: y(lastC), r: 2.6}));
  for (const p of holds) {
    for (const [v, cls, ko] of [[p.entry, "entry", `${p.bot} 진입`], [p.stop, "stop", "손절"]]) {
      if (!ok(v)) continue;
      kids.push(s("line", {class: ["dk-hl", cls], x1: 0, x2: W, y1: y(Number(v)), y2: y(Number(v))}),
        s("text", {class: ["dk-hlt", cls], x: 4, y: y(Number(v)) - 3}, `${ko} ${pxKo(v)}`));
    }
  }
  // the 30m trend strip: each 30m bar over the 15m bars it covers
  const t0 = bars[0][0], t1 = bars[n - 1][0] + MIN15;
  for (const [t, tr] of c.trend30 || []) {
    if (t + 30 * MIN <= t0 || t >= t1) continue;
    const xa = Math.max(0, ((t - t0) / (t1 - t0)) * W), xb = Math.min(W, ((t + 30 * MIN - t0) / (t1 - t0)) * W);
    kids.push(s("rect", {class: ["dk-strip", toneOf(tr)], x: xa, width: Math.max(0.5, xb - xa - 0.6), y: strip, height: 10}));
  }
  kids.push(s("text", {class: "dk-axis", x: 2, y: strip - 4}, `${TM_KO} 30분 (0선 위 초록 · 아래 빨강)`),
    s("text", {class: "dk-axis", x: 2, y: H - 4}, fmt.kst(t0)), s("text", {class: "dk-axis", x: W - 2, y: H - 4, "text-anchor": "end"}, fmt.kst(t1)));
  return s("svg", {class: "dk-chart", viewBox: VB(W, H), width: W, height: H, role: "img",
    "aria-label": `${c.coin} 15분봉 ${n}개와 30분 ${TM_KO}`}, kids);
}

/** The chosen coin's histogram on its 15m bars (green above 0, red below, the crosses marked). */
function histSvg(c, W = 600) {
  const H = 150, mid = 75;
  const v = (c.hist || []).map((x) => (ok(x) ? Number(x) : 0));
  if (!v.length) return ui.empty("히스토그램이 없어요");
  const m = Math.max(...v.map(Math.abs), 1e-9), bw = W / v.length;
  const kids = [s("line", {class: "dk-zero", x1: 0, x2: W, y1: mid, y2: mid})];
  v.forEach((x, i) => {
    const hh = (Math.abs(x) / m) * (mid - 8);
    kids.push(s("rect", {class: ["dk-hbar", x >= 0 ? "up" : "down"], x: i * bw + bw * 0.12, width: Math.max(1, bw * 0.76), y: x >= 0 ? mid - hh : mid, height: Math.max(0.5, hh)}));
    const x0 = (c.cross || [])[i];
    if (x0) kids.push(s("circle", {class: ["dk-hx", x0 > 0 ? "up" : "down"], cx: i * bw + bw / 2, cy: x0 > 0 ? mid - hh - 6 : mid + hh + 6, r: 3}));
  });
  return s("svg", {class: "dk-hist", viewBox: VB(W, H), width: W, height: H, role: "img", "aria-label": `${c.coin} 히스토그램`}, kids);
}

/** 신호 흐름: the last 48 hours by 15m: the bots' signals (bars) and entries (dots). */
function flowSvg(flow, W = 600) {
  const H = 140, base = 116, imp = 22;
  const f = flow || [];
  if (!f.length) return ui.empty("기록이 없어요");
  const m = Math.max(1, ...f.map((x) => x[1])), bw = W / f.length;
  const sum = f.map((_x, i) => f.slice(Math.max(0, i - 7), i + 1).reduce((a, x) => a + (Number(x[1]) || 0), 0));   // 8 × 15m
  const ms = Math.max(1, ...sum), ya = (v) => base - imp - 4 - (v / ms) * (base - imp - 14);
  const line = sum.map((v, i) => `${i ? "L" : "M"}${(i * bw + bw / 2).toFixed(1)},${ya(v).toFixed(1)}`).join("");
  const kids = [s("line", {class: "dk-zero", x1: 0, x2: W, y1: base, y2: base}),
    s("path", {class: "dk-farea", d: `${line}L${(W - bw / 2).toFixed(1)},${base - imp - 4}L${(bw / 2).toFixed(1)},${base - imp - 4}Z`}),
    s("path", {class: "dk-fline", d: line})];
  f.forEach((x, i) => {
    const hh = (x[1] / m) * imp;
    if (x[1]) kids.push(s("rect", {class: "dk-fbar", x: i * bw, width: Math.max(1, bw * 0.7), y: base - hh, height: hh}));
    if (x[2]) kids.push(s("circle", {class: "dk-fent", cx: i * bw + bw / 2, cy: ya(sum[i]), r: 3}));
  });
  kids.push(s("text", {class: "dk-axis", x: 2, y: H - 4}, `${fmt.kst(f[0][0])}`), s("text", {class: "dk-axis", x: W - 2, y: H - 4, "text-anchor": "end"}, "지금"));
  return s("svg", {class: "dk-flow", viewBox: VB(W, H), width: W, height: H, role: "img", "aria-label": "48시간 신호와 진입"}, kids);
}

/** 코인 흐름 · FEED (the pictures' feed chart): the six coins' last 24 hours as % from where each began, a colour a coin,
 *  each line's last value tagged at its end (the tags nudged apart). */
function feedSvg(coins, W = 600) {
  const H = 176, top = 10, bot = 154, L = 44, Rm = 92;
  const ls = feedLines(coins);
  if (!ls.length) return ui.empty("봉이 없어요");
  const vs = ls.flatMap((o) => o.pts.map((p) => p[1])), lo = Math.min(0, ...vs), hi = Math.max(0, ...vs), sp = hi - lo || 0.01;
  const n = Math.max(1, ...ls.map((o) => o.pts.length - 1));
  const x = (i) => L + (i / n) * (W - L - Rm), y = (v) => top + (1 - (v - lo) / sp) * (bot - top);
  const kids = [];
  for (let g = 0; g <= 3; g++) {
    const v = lo + (sp * g) / 3;
    kids.push(s("line", {class: "dk-gridl", x1: L, x2: W - Rm, y1: y(v), y2: y(v)}), s("text", {class: "dk-axis", x: 2, y: y(v) + 3}, pctKo(v, 1)));
  }
  kids.push(s("line", {class: "dk-zero", x1: L, x2: W - Rm, y1: y(0), y2: y(0)}));
  for (const o of ls) kids.push(s("path", {class: ["dk-feedl", CID(o.k)], d: o.pts.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("")}));
  const tags = ls.map((o) => ({o, ty: y(o.last)})).sort((a, b) => a.ty - b.ty);
  for (let i = 1; i < tags.length; i++) tags[i].ty = Math.max(tags[i].ty, tags[i - 1].ty + 12);
  const over = tags.length ? tags[tags.length - 1].ty - (H - 14) : 0;
  if (over > 0) for (const t of tags) t.ty = Math.max(8, t.ty - over);
  for (const {o, ty} of tags) kids.push(s("text", {class: ["dk-feedt", CID(o.k)], x: W - Rm + 6, y: ty + 3}, `${o.coin} ${pctKo(o.last, 1)}`));
  kids.push(s("text", {class: "dk-axis", x: L, y: H - 4}, "24시간 전"), s("text", {class: "dk-axis", x: W - Rm, y: H - 4, "text-anchor": "end"}, "지금"));
  return s("svg", {class: "dk-feed", viewBox: VB(W, H), width: W, height: H, role: "img", "aria-label": "여섯 코인 24시간 흐름 (처음 대비 %)"}, kids);
}

/** 포워드 테스트: each bot's balance in % from its start, the line where the new rules began. */
function fwdSvg(bots, split, W = 600) {
  const H = 240, top = 16, bot = 214;
  const lines = bots.map((b) => ({id: b.id, name: b.name_ko, c: pctCurve(b.curve)})).filter((x) => x.c.length > 1);
  if (!lines.length) return null;
  const ts = lines.flatMap((x) => x.c.map((p) => p[0])), vs = lines.flatMap((x) => x.c.map((p) => p[1]));
  const t0 = Math.min(...ts), t1 = Math.max(...ts, serverNow()), lo = Math.min(0, ...vs), hi = Math.max(0, ...vs), sp = hi - lo || 0.01;
  const L = 44;                                        // the axis words sit in a left margin, clear of the lines
  const x = (t) => L + ((t - t0) / (t1 - t0 || 1)) * (W - L), y = (v) => top + (1 - (v - lo) / sp) * (bot - top);
  const kids = [];
  for (let g = 0; g <= 4; g++) {
    const v = lo + (sp * g) / 4;
    kids.push(s("line", {class: "dk-gridl", x1: L, x2: W, y1: y(v), y2: y(v)}), s("text", {class: "dk-axis", x: 2, y: y(v) + 3}, pctKo(v, 1)));
  }
  if (ok(split) && split > t0 && split < t1) {
    kids.push(s("rect", {class: "dk-oos", x: x(split), y: top, width: W - x(split), height: bot - top}),
      s("line", {class: "dk-split", x1: x(split), x2: x(split), y1: top - 6, y2: bot}),
      x(split) - L > 70 ? s("text", {class: "dk-fwdk", x: x(split) - 6, y: top + 12, "text-anchor": "end"}, "이전 규칙") : null,
      s("text", {class: ["dk-fwdk", "new"], x: x(split) + 6, y: top + 12}, `새 규칙 (${fmt.kst(split)}부터)`));
  }
  lines.forEach((ln, k) => {
    const d = ln.c.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
    kids.push(s("path", {class: ["dk-fwdl", `b${k}`], d}));
    const last = ln.c[ln.c.length - 1];
    kids.push(s("circle", {class: ["dk-fwdp", `b${k}`], cx: x(last[0]), cy: y(last[1]), r: 3.5}));
  });
  return s("svg", {class: "dk-fwd", viewBox: VB(W, H), width: W, height: H, role: "img", "aria-label": "봇별 잔고 변화 (시작 대비 %)"}, kids);
}

/** 목표 ×6: the path to ×target over the month (dashed), each bot's month in multiples of its month-start balance, today. */
function goalSvg(g, bots, W = 600) {
  const H = 190, top = 12, bot = 166, L = 40;
  const n = Number(g.month_days) || 30, T = Number(g.target) || 6;
  const lines = (g.bots || []).filter((x) => x.state === "ok" && x.month).map((x) => {
    const k = (bots || []).findIndex((b) => b.id === x.id);
    return {k, pts: monthLine(((bots || [])[k] || {}).curve, x.month, serverNow())};
  }).filter((o) => o.pts.length > 1);
  const ms = lines.flatMap((o) => o.pts.map((p) => p[1]));
  const hiM = Math.max(T, ...ms), loM = Math.min(1, ...ms) * 0.95;
  const ly = (m) => Math.log(Math.max(Number(m), 1e-3)), sp = ly(hiM) - ly(loM) || 1;
  const y = (m) => top + (1 - (ly(m) - ly(loM)) / sp) * (bot - top);
  const x = (d) => L + (Math.min(n, Math.max(0, d)) / n) * (W - L - 8);
  const kids = [];
  for (const m of [1, 2, 3, T].filter((v, i, a) => v <= hiM && a.indexOf(v) === i)) {      // (a log scale: ×4, ×5 would crowd ×6)
    kids.push(s("line", {class: "dk-gridl", x1: L, x2: W, y1: y(m), y2: y(m)}), s("text", {class: "dk-axis", x: 2, y: y(m) + 3}, `×${m}`));
  }
  for (const d of [0, 10, 20, n]) kids.push(s("text", {class: "dk-axis", x: x(d), y: H - 4, "text-anchor": d === 0 ? "start" : d === n ? "end" : "middle"}, `${d}일`));
  const path = [];
  for (let d = 0; d <= n; d += 0.5) path.push(`${d ? "L" : "M"}${x(d).toFixed(1)},${y(pathAt(T, d, n)).toFixed(1)}`);
  kids.push(s("path", {class: "dk-gpath", d: path.join("")}), s("text", {class: "dk-gtag", x: x(n) - 2, y: y(T) - 5, "text-anchor": "end"}, `목표 ×${fmt.num(T, 0)}`));
  const today = ok(g.from_ms) ? (serverNow() - Number(g.from_ms)) / 86400000 : null;
  if (ok(today) && today >= 0 && today <= n) {
    kids.push(s("line", {class: "dk-gnow", x1: x(today), x2: x(today), y1: top, y2: bot}),
      s("text", {class: "dk-axis", x: x(today) + 4, y: top + 9}, `오늘 · 경로 ${multKo(pathAt(T, today, n))}`));
  }
  for (const o of lines) {
    kids.push(s("path", {class: ["dk-fwdl", `b${o.k}`], d: o.pts.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("")}));
    const last = o.pts[o.pts.length - 1];
    kids.push(s("circle", {class: ["dk-fwdp", `b${o.k}`], cx: x(last[0]), cy: y(last[1]), r: 3.5}));
  }
  return s("svg", {class: "dk-gsvg", viewBox: VB(W, H), width: W, height: H, role: "img", "aria-label": `이번 달 잔고 배수와 ×${fmt.num(T, 0)} 경로`}, kids);
}

// ---------------------------------------------------------------- the core: an attractor's flow inside a shell of points
// The owners' picture ("코어 동그라미도 사진과 같이 이렇게 멋지게 움직이는거처럼", "동그라미 이색깔로"): a dotted shell with orbit
// rings, glowing stars joined by thin lines, and a swirling flow inside, in the picture's colours (a sand tube up the axis,
// cyan and blue swirls round it). The flow is the Aizawa system (a well-known chaotic attractor): its shape, the stars and
// the particle colours are decoration, never a model of the market. What carries data: the fans from the left, one per
// coin in the colour of its 30m 추세 MACD (owners 11-02; the 추세 바 종합 before); the coin whose histogram crossed 0 at the last 15m close drawn white; the held
// coin's particles amber, pulsing; the fans to the right, one per recent close (won green, lost red); the probes' values.
const AZ = {a: 0.95, b: 0.7, c: 0.6, d: 3.5, e: 0.25, f: 0.1};
const AZ_DT = 0.011;
const ROLL = 0.28;                                   // the core's lean on screen (radians), as in the owners' picture
/** One Euler step of the Aizawa system (pure; tests: tests/test_dash_livedeck.py). */
export function aizawa(p, dt = AZ_DT) {
  const {a, b, c, d, e, f} = AZ, [x, y, z] = p;
  const dx = (z - b) * x - d * y, dy = d * x + (z - b) * y;
  const dz = c + a * z - (z * z * z) / 3 - (x * x + y * y) * (1 + e * z) + f * z * x * x * x;
  return [x + dx * dt, y + dy * dt, z + dz * dt];
}
function coreView(ctx) {
  const pin = {position: "absolute", left: "0", top: "0", width: "100%", height: "100%", display: "block"};
  const cvT = h("canvas", {class: "dk-corec", "aria-hidden": "true", style: pin});       // the flow, with its trails
  const cvS = h("canvas", {class: "dk-corec", "aria-hidden": "true", style: pin});       // the shell, the rings, the lines
  const gT = cvT.getContext ? cvT.getContext("2d") : null, gS = cvS.getContext ? cvS.getContext("2d") : null;
  const probe = (cls) => h("div", {class: ["dk-probe", cls]}, h("small", {class: "dk-mono"}), h("b", {class: "num"}), h("small"));
  const pA = probe("a"), pB = probe("b"), pC = probe("c");
  const box = h("div", {class: "dk-corebox", style: {position: "relative", overflow: "hidden"}}, cvT, cvS, pA, pB, pC);
  const o = {flow: [], shell: [], stars: [], W: 0, H: 0, dpr: 1, ang: 0.6, raf: 0, last: 0, alive: true, col: null, coins: [], hot: null, hold: null, fills: [], n: 0};
  const tok = () => {
    const cs = getComputedStyle(document.documentElement), v = (k) => String(cs.getPropertyValue(k) || "").trim();
    o.col = {up: v("--dk-green"), down: v("--dk-red"), flat: v("--dk-amber"), na: v("--dk-muted"), ring: v("--dk-cyan"), gold: v("--dk-gold"),
      hold: v("--dk-amber"), hi: v("--dk-spark"), steel: v("--dk-steel"), mauve: v("--dk-mauve"), cyan: v("--dk-core-cyan"),
      blue: v("--dk-core-blue"), sand: v("--dk-core-sand"), pink: v("--dk-core-pink"), violet: v("--dk-core-violet")};
  };
  function seed(n) {                                   // particles spread over the attractor (warmed up from scattered starts)
    const out = [];
    let q = [0.1, 0, 0];
    for (let i = 0; i < 400; i++) q = aizawa(q);
    for (let i = 0; i < n; i++) {
      for (let k = 0; k < 7; k++) q = aizawa(q);
      out.push({p: [q[0] + (i % 13) * 1e-4, q[1], q[2]], coin: i % 6, j: ((i * 7919) % 101) / 101});
    }
    return out;
  }
  // the picture's shell colours: mostly glowing cyan, then blue, some muted teal, a little sand, a rare pink speck, white sparkles
  const SHELL_MIX = [[0.46, "cyan"], [0.72, "blue"], [0.84, "ring"], [0.91, "sand"], [0.94, "pink"], [1, "hi"]];
  const STAR_TONES = ["hi", "cyan", "sand", "pink", "hi", "violet", "blue", "sand", "hi", "cyan"];
  function starPts(n) {                               // the picture's glowing nodes and the thin lines between them (decoration)
    const pts = [];
    for (let i = 0; i < n; i++) {
      const u = ((i * 7907) % 1009) / 1009, w = ((i * 6151) % 1013) / 1013, q = ((i * 3571) % 997) / 997;
      const th = u * Math.PI * 2, ph = Math.acos(2 * w - 1), rr = 0.3 + 1.5 * Math.sqrt(q);
      pts.push({v: [Math.sin(ph) * Math.cos(th) * rr, Math.cos(ph) * rr * 0.8, Math.sin(ph) * Math.sin(th) * rr],
        tone: STAR_TONES[i % STAR_TONES.length], big: q > 0.7, nb: []});
    }
    for (const a of pts) {                             // each node joins its two nearest
      const d = pts.filter((b) => b !== a).map((b) => [Math.hypot(a.v[0] - b.v[0], a.v[1] - b.v[1], a.v[2] - b.v[2]), b]);
      d.sort((x, y) => x[0] - y[0]);
      a.nb = d.slice(0, 2).map((x) => x[1]);
    }
    return pts;
  }
  function shellPts(n) {                              // a dust sphere: jittered radius, a band phase per point, a colour per point
    const pts = [], ga = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {
      const yy = 1 - (i / (n - 1)) * 2, r = Math.sqrt(1 - yy * yy), th = ga * i;
      const j = ((i * 2654435761) % 1000) / 1000, rr = 1 + (j - 0.5) * 0.09, hue = ((i * 40503) % 997) / 997;
      pts.push({v: [Math.cos(th) * r * rr, yy * rr, Math.sin(th) * r * rr], lat: Math.asin(yy), lon: th, j,
        tone: SHELL_MIX.find((m) => hue < m[0])[1]});
    }
    return pts;
  }
  function layout() {
    const r = box.getBoundingClientRect ? box.getBoundingClientRect() : {width: 0, height: 0};
    const dpr = Math.min(2, (typeof window !== "undefined" && window.devicePixelRatio) || 1);
    const W = Math.round(Math.min(r.width, 1800) * dpr), H = Math.round(Math.min(r.height, 900) * dpr);
    if (W === o.W && H === o.H) return false;
    o.W = W; o.H = H; o.dpr = dpr;
    for (const c of [cvT, cvS]) { c.width = Math.max(1, W); c.height = Math.max(1, H); }
    const n = r.width < 520 ? 3600 : 9000;
    if (n !== o.n) { o.n = n; o.flow = seed(n); o.shell = shellPts(r.width < 520 ? 1400 : 3200); o.stars = starPts(r.width < 520 ? 30 : 64); }
    return true;
  }
  const reduced = () => motion.reduced();
  const running = () => o.alive && cvT.isConnected && !document.hidden && !reduced() && !!gT;
  const view = () => {
    const R = Math.min(o.W * 0.36, o.H * 0.44);
    return {R, cx: o.W / 2, cy: o.H / 2, ca: Math.cos(o.ang), sa: Math.sin(o.ang), ct: Math.cos(0.42), st: Math.sin(0.42),
      cr: Math.cos(ROLL), sr: Math.sin(ROLL)};
  };
  // a point in the attractor's frame (x, y across, z up) -> the screen
  const proj = (v, x, yy, z) => {
    const x1 = x * v.ca - yy * v.sa, d1 = x * v.sa + yy * v.ca;
    const y2 = z * v.ct + d1 * v.st, d2 = -z * v.st + d1 * v.ct;
    const k = 3 / (3 + d2);                              // then the picture's lean: its top tipped to the right
    return [v.cx + (x1 * v.cr + y2 * v.sr) * k * v.R, v.cy - (y2 * v.cr - x1 * v.sr) * k * v.R, d2];
  };
  function drawShell(t) {
    if (!gS || !o.col) return;
    const c = o.col, v = view(), dpr = o.dpr, tt = (t || 0) / 1000;
    gS.setTransform(1, 0, 0, 1, 0, 0);
    gS.clearRect(0, 0, o.W, o.H);
    // the fans of thin lines from each coin's box (left) into the shell, in the coin's 30m trend colour
    gS.lineWidth = Math.max(1, dpr * 0.7);
    for (let i = 0; i < 6; i++) {
      const cn = o.coins[i];
      const ey = o.H * (0.09 + i * 0.165);
      const hot = cn && (cn.sym === o.hot || cn.sym === o.hold);
      gS.strokeStyle = cn && cn.sym === o.hold ? c.hold : c[cn ? cn.tone : "na"] || c.na;
      for (let k = 0; k < 5; k++) {
        const a = (k - 2) * 0.19 + (i - 2.5) * 0.12, tx = v.cx - Math.cos(a) * v.R * 0.98, ty = v.cy + Math.sin(a) * v.R * 0.98;
        gS.globalAlpha = (hot ? 0.55 : 0.16) * (1 - Math.abs(k - 2) * 0.18);
        gS.beginPath(); gS.moveTo(0, ey);
        gS.bezierCurveTo(o.W * 0.16, ey, tx - v.R * 0.55, ty, tx, ty);
        gS.stroke();
      }
    }
    // the fans out to the right, one per recent close (the late fills beside the core), green won / red lost
    o.fills.forEach((tone, i) => {
      const ey = o.H * (0.08 + i * 0.12);
      gS.strokeStyle = c[tone] || c.na;
      for (let k = 0; k < 3; k++) {
        const a = (k - 1) * 0.16 + (i - 3) * 0.1, tx = v.cx + Math.cos(a) * v.R * 0.98, ty = v.cy + Math.sin(a) * v.R * 0.98;
        gS.globalAlpha = 0.2 * (1 - Math.abs(k - 1) * 0.3);
        gS.beginPath(); gS.moveTo(tx, ty);
        gS.bezierCurveTo(tx + v.R * 0.55, ty, o.W * 0.84, ey, o.W, ey);
        gS.stroke();
      }
    });
    // the orbit rings (thin, turning slowly)
    gS.lineWidth = dpr;
    for (const [rx, ry, rot, al] of [[1.34, 0.28, -0.42, 0.3], [1.22, 0.44, 0.55, 0.18], [1.5, 0.14, 0.12, 0.14]]) {
      gS.globalAlpha = al; gS.strokeStyle = c.ring;
      gS.beginPath(); gS.ellipse(v.cx, v.cy, v.R * rx, v.R * ry, rot + Math.sin(tt / 9) * 0.08, 0, Math.PI * 2); gS.stroke();
    }
    // the dust shell: brightest at its rim and on its lit lower right (as in the picture), in drifting bands; painted over,
    // not added, so the cyan and blue stay cyan and blue
    gS.globalCompositeOperation = "source-over";
    const sv = {...v, ca: Math.cos(-o.ang * 0.7), sa: Math.sin(-o.ang * 0.7)};
    for (const q of o.shell) {
      const [X, Y, D] = proj(sv, q.v[0] * 1.24, q.v[2] * 1.16, q.v[1] * 1.12);       // a little wider than tall
      const rim = 1 - Math.min(1, Math.abs(D) / 1.16);                 // 1 at the silhouette, 0 facing us
      const band = 0.55 + 0.45 * Math.sin(q.lat * 7 + q.lon * 1.0 + tt * 0.6);      // swirling bands, as in the picture
      const lit = Math.max(0, ((X - v.cx) * 0.5 + (Y - v.cy) * 0.86) / (v.R * 1.16));   // light from the lower right
      const front = D < 0 ? 1 : 0.55, glint = q.tone === "hi";
      gS.globalAlpha = Math.min(1, (0.08 + 0.62 * rim * rim + 0.16 * band + 0.3 * lit * rim) * front * (0.7 + 0.3 * q.j) * (glint ? 1.3 : 1));
      gS.fillStyle = c[q.tone] || c.ring;
      const sz = (glint ? 1.7 : 1.1 + 0.9 * rim) * dpr;
      gS.fillRect(X - sz / 2, Y - sz / 2, sz, sz);
    }
    // the stars: glowing nodes joined by thin lines, turning with the shell
    const sp = o.stars.map((q) => proj(sv, q.v[0] * 1.16, q.v[2] * 1.16, q.v[1] * 1.16));
    gS.globalCompositeOperation = "source-over";
    gS.lineWidth = Math.max(1, dpr * 0.6); gS.strokeStyle = c.steel;
    o.stars.forEach((q, i) => q.nb.forEach((b) => {
      const k = o.stars.indexOf(b);
      if (k < i && b.nb.includes(q)) return;           // each pair once
      gS.globalAlpha = 0.3; gS.beginPath(); gS.moveTo(sp[i][0], sp[i][1]); gS.lineTo(sp[k][0], sp[k][1]); gS.stroke();
    }));
    gS.globalCompositeOperation = "lighter";
    o.stars.forEach((q, i) => {
      const [X, Y, D] = sp[i], tw = 0.75 + 0.25 * Math.sin(tt * 1.3 + i * 1.7), r0 = (q.big ? 2.2 : 1.5) * dpr;
      gS.fillStyle = c[q.tone] || c.hi;
      gS.globalAlpha = 0.16 * tw * (D < 0 ? 1 : 0.6);
      gS.beginPath(); gS.arc(X, Y, r0 * 3.2, 0, Math.PI * 2); gS.fill();
      gS.globalAlpha = 0.95 * tw * (D < 0 ? 1 : 0.6);
      gS.beginPath(); gS.arc(X, Y, r0, 0, Math.PI * 2); gS.fill();
    });
    gS.globalCompositeOperation = "source-over";
    gS.globalAlpha = 1;
  }
  function drawFlow(t, fade) {
    if (!gT || !o.col) return;
    const c = o.col, v = view(), dpr = o.dpr;
    gT.setTransform(1, 0, 0, 1, 0, 0);
    if (fade) {                                        // the trails: the last frames fade out
      gT.globalCompositeOperation = "destination-out";
      gT.globalAlpha = 0.42; gT.fillRect(0, 0, o.W, o.H);   // short trails: grains, as in the picture
    } else gT.clearRect(0, 0, o.W, o.H);
    gT.globalCompositeOperation = "source-over";       // painted over, so the sand stays sand and the cyan stays cyan
    const pulse = 0.55 + 0.45 * Math.sin((t || 0) / 280);
    for (const pt of o.flow) {
      const cn = o.coins[pt.coin];
      const held = cn && cn.sym === o.hold, hot = cn && cn.sym === o.hot;
      // the attractor's frame: x, y across, z up (centred on its middle, z ~ 0.64); the axis tube drawn wider, as in the picture
      const r = Math.hypot(pt.p[0], pt.p[1]), w = r > 1e-6 ? (Math.pow(r, 0.55) / r) * 0.72 : 0.72;
      const [X, Y, D] = proj(v, pt.p[0] * w, pt.p[1] * w, (pt.p[2] - 0.64) * 0.62);
      const f = Math.max(0, Math.min(1, (1.2 - D) / 2.4));
      let a = (0.18 + 0.62 * f) * (0.7 + 0.3 * pt.j);   // the held coin amber, the hot coin white
      if (hot) a = Math.min(1, a * 1.7);
      if (held) a *= pulse;
      gT.globalAlpha = a;
      // the picture's colours: a sand tube up the axis, cream where it opens at the top, cyan and blue swirls round it and
      // on the disk at its foot
      const z = pt.p[2], tube = r < 0.26 && z > -0.15, lip = r < 0.5 && z > 1.2;
      const tone = tube ? (pt.j > 0.94 ? "hi" : "sand") : lip ? (pt.j < 0.6 ? "sand" : "hi") : pt.j > 0.96 ? "hi" : pt.j < 0.55 ? "cyan" : "blue";
      gT.fillStyle = held ? c.hold : hot ? c.hi : c[tone];
      const sz = (0.7 + 1.3 * f) * dpr * (hot ? 1.35 : 1);
      gT.fillRect(X - sz / 2, Y - sz / 2, sz, sz);
    }
    gT.globalAlpha = 1;
    gT.globalCompositeOperation = "source-over";
  }
  function step(n = 2) {
    for (const pt of o.flow) {
      for (let k = 0; k < n; k++) pt.p = aizawa(pt.p);
      if (!Number.isFinite(pt.p[0]) || Math.abs(pt.p[0]) > 4 || Math.abs(pt.p[2]) > 4) pt.p = [0.1 + pt.j * 0.2, 0, 0];
    }
  }
  function frame(t) {
    o.raf = 0;
    if (!running()) return;
    if (t - o.last >= FRAME_MS) {
      const dt = o.last ? Math.min(120, t - o.last) : 0;
      o.last = t;
      o.ang += dt * 0.00034;                           // (owners 11-01, their video: the core turns visibly)
      step(3);
      drawShell(t);
      drawFlow(t, true);
    }
    o.raf = requestAnimationFrame(frame);
  }
  const kick = () => { if (!o.raf && running()) { o.last = 0; o.raf = requestAnimationFrame(frame); } };
  const still = () => { layout(); drawShell(0); drawFlow(0, false); };
  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => { if (layout()) { if (running()) kick(); else still(); } });
    ro.observe(box);
    ctx.track(() => ro.disconnect());
  }
  ctx.listen(document, "visibilitychange", () => { if (!document.hidden) { tok(); if (running()) kick(); else still(); } });
  ctx.track(() => { o.alive = false; if (o.raf) cancelAnimationFrame(o.raf); o.raf = 0; });
  requestAnimationFrame(() => { tok(); layout(); if (running()) kick(); else still(); });
  const setProbe = (el, x) => {
    const [k, b, sm] = el.children;
    k.textContent = x.k; b.textContent = x.v; sm.textContent = x.s || "";
    b.className = ["num", x.tone || ""].join(" ");
  };
  return {
    el: box,
    set(coins, hot, hold, probes, fills) {
      o.coins = coins; o.hot = hot; o.hold = hold; o.fills = fills || [];
      if (probes) { setProbe(pA, probes[0]); setProbe(pB, probes[1]); setProbe(pC, probes[2]); }
      if (!o.raf) { if (running()) kick(); else still(); }
    },
  };
}

// ---------------------------------------------------------------- the screen
const panel = (cls, title, sub, ...body) => h("section", {class: ["dk-p", cls]},
  h("header", {class: "dk-ph"}, h("b", {class: "dk-pt"}, "◆ ", title), sub ? h("span", {class: "dk-ps"}, sub) : null), ...body);

export function deckView(ctx) {
  const st = {d: null, okAt: 0, busy: false, sel: null};
  const slot = h("div", {class: "lb-slot"});
  const clockK = h("b", {class: "dk-clk num"}, "--:--:--"), clockU = h("small", {class: "dk-clku num"}, "");
  const prices = h("div", {class: "dk-prices"});
  const tickIn = h("div", {class: "dk-tickin"});
  const footIn = h("div", {class: "dk-tickin"});
  const wallet = h("div", {class: "dk-wallet"});
  const coinTabs = h("div", {class: "dk-ctabs", role: "tablist", "aria-label": "코인 고르기"});
  const chart = h("div", {class: "dk-chartbox"});
  const chartSub = h("span");
  const botsBox = h("div", {class: "dk-bots"});
  const gridBox = h("div", {class: "dk-grid"});
  const lifeBox = h("div", {class: "dk-life"});
  const goalBox = h("div", {class: "dk-goal"});
  const goalSub = h("span");
  const cardBox = h("div", {class: "dk-cardbox"});
  const cardSub = h("span");
  const inputs = h("div", {class: "dk-inputs"});
  const fills = h("div", {class: "dk-fills"});
  const core = coreView(ctx);
  const tape = h("div", {class: "dk-tape"});
  const fwd = h("div", {class: "dk-fwdbox"});
  const hist = h("div", {class: "dk-histbox"});
  const histSub = h("span");
  const flow = h("div", {class: "dk-flowbox"});
  const feedBox = h("div", {class: "dk-feedbox"}), wire = h("div", {class: "dk-wire"}), feedStats = h("div", {class: "dk-fstats"});
  // the numbers that count to a new value (core/motion.js countTo: only on a real change, the first paint at once)
  const eqLed = h("div", {class: "dk-led num"}, "—"), gMult = h("b", {class: "num"}, "—"), gNeed = h("b", {class: "num"}, "—");
  // owners 11-01 "다 해줘": the price now (the card's 지금 row, the source line under the clock), 위험, 이번 달, the alerts
  const cardNow = h("div", {class: "dk-crow now"});
  const pxSrc = h("small", {class: "dk-clku dk-pxsrc"}, "가격 · 끝난 15분봉");
  const riskBox = h("div", {class: "dk-riskbox"}), calBox = h("div", {class: "dk-calbox"}), calSub = h("span");
  const toast = h("div", {class: "dk-toast", role: "status", "aria-live": "polite", hidden: true});
  const grid = h("div", {class: "dk-g"},
    panel("dk-a-wal", "지갑 · WALLET", "봇 합계 · 봇 기록 그대로", wallet),
    panel("dk-a-cht", "코인 차트 · SPOT", chartSub, coinTabs, chart),
    panel("dk-a-fee", "코인 흐름 · FEED", "여섯 코인 24시간 · 처음 대비 % · 아래는 봇 기록 원문",
      h("div", {class: "dk-feedwrap"}, h("div", {class: "dk-feedmain"}, feedBox, h("small", {class: "dk-mono"}, "WIRE · 봇 기록 원문 (최근 7)"), wire), feedStats)),
    panel("dk-a-grd", "추세 그리드 · TREND GRID", "봇 × 코인 · 마지막 마감에 본 30분 추세 MACD와 신호", gridBox),
    panel("dk-a-lif", "포지션 진행 · LIFECYCLE", "손절 → 진입 → 다음 계단 · 지금 가격", lifeBox),
    panel("dk-a-bot", "봇 상태 · BOT STATUS", "실거래 · 모의 쌍둥이", botsBox),
    panel("dk-a-crd", "진입 카드 · ENTRY CARD", cardSub, cardBox),
    panel("dk-a-rsk", "위험 · RISK", "열린 포지션 · 지금 가격 기준 · 이번 달", riskBox),
    panel("dk-a-gol", "목표 ×6 · GOAL PACE", goalSub, goalBox),
    panel("dk-a-cal", "이번 달 · CALENDAR", calSub, calBox),
    panel("dk-a-cor", "코어 · ATTRACTOR CORE", "왼쪽 선 = 코인 (색 = 30분 추세 MACD) · 흰 입자 = 방금 진입 신호 자리 · 주황 입자 = 포지션 · 오른쪽 선 = 최근 청산 · 흐름 모양·별·입자 색은 장식(Aizawa 흐름)",
      h("div", {class: "dk-corewrap"}, inputs, core.el, fills)),
    panel("dk-a-tap", "실행 기록 · EXECUTION TAPE", "봇들의 신호 · 진입 · 계단 · 청산 · 건너뜀", tape),
    panel("dk-a-fwd", "포워드 테스트 · FORWARD TEST", "새 규칙 전과 후 · 시작 대비 잔고", fwd),
    panel("dk-a-his", "히스토그램 · HISTOGRAM", histSub, hist),
    panel("dk-a-flo", "신호 흐름 · SIGNAL CASCADE", "48시간 · 15분마다 신호(0선 돌파 · OBV 히스토그램 전환, 아래 막대) · 2시간 합(금색) · 진입(점)", flow));
  // the opening (owners 11-01 "동영상처럼"): the head, the running line and the panels come up one after another (--i);
  // the class goes once they are up, so the 15 s redraws never replay it
  grid.childNodes.forEach((p, i) => { if (p.style && p.style.setProperty) p.style.setProperty("--i", String(i + 2)); });
  const el = h("div", {class: ["dk", "boot"]},
    slot,
    h("header", {class: "dk-top", style: {"--i": 0}},
      h("div", {class: "dk-brand"}, h("span", {class: "dk-logo", "aria-hidden": "true"}, "PB"),
        h("div", null, h("small", {class: "dk-mono"}, "WOO X PRO 1 · 2 · 15M ENTRY · 30M TREND MACD · ONE POSITION EACH"),
          h("b", {class: "dk-name"}, "PAPERBOT ", h("em", null, "//"), " 관제실"),
          h("small", {class: "dk-mono"}, "바이비트 봇 · 친구 15분 봇 · 레인지 봇 — 보기만 하는 화면"))),
      prices,
      h("div", {class: "dk-clock"}, h("div", null, clockK, h("span", {class: "dk-live"}, "LIVE")), h("small", {class: "dk-mono"}, "KST · 한국 시간"), clockU, pxSrc)),
    h("div", {class: "dk-tick", "aria-label": "봇 기록 흐름", style: {"--i": 1}}, tickIn),
    grid,
    h("div", {class: "dk-tick dk-foot", "aria-label": "요약 흐름"}, footIn),
    ui.note("보기만 하는 화면 · 15초마다 새로 읽어요 · 숫자는 모두 봇 기록과 바이낸스 봉이에요 (꾸민 숫자 없음)"));

  el.append(toast);
  function tickClock() {
    const now = serverNow();
    const k = new Date(now + 9 * 3600 * 1000), u = new Date(now);
    const two = (x) => String(x).padStart(2, "0");
    clockK.textContent = `${two(k.getUTCHours())}:${two(k.getUTCMinutes())}:${two(k.getUTCSeconds())}`;
    clockU.textContent = `${two(u.getUTCHours())}:${two(u.getUTCMinutes())} UTC · 다음 15분 마감 ${mmss(nextClose(now).left_ms)}`;
    for (const box of [lifeBox, feedStats]) for (const x of box.querySelectorAll("[data-wait]")) x.textContent = mmss(nextClose(now).left_ms);
  }
  /** A panel's width in px (the charts are drawn 1:1 so their words keep their size on a phone). */
  const wOf = (box) => Math.max(260, Math.round((box.getBoundingClientRect ? box.getBoundingClientRect().width : 0) || 600));
  const coinOf = (sym) => (st.d && (st.d.coins || []).find((c) => c.symbol === sym)) || null;
  const holdsOf = (sym) => ((st.d && st.d.bots) || []).filter((b) => b.position && b.position.state === "ok" && b.position.symbol === sym)
    .map((b) => ({bot: b.name_ko, entry: b.position.entry, stop: b.position.stop}));

  function drawTop(d) {
    const was = st.pxWas || {}, now = {};
    for (const c of d.coins || []) { const q = pn(c); if (q) now[c.symbol] = q; }
    st.pxWas = Object.fromEntries(Object.entries(now).map(([k, q]) => [k, q.px]));
    const fl = (c) => (ok(was[c.symbol]) && now[c.symbol] && was[c.symbol] !== now[c.symbol].px ? (now[c.symbol].px > was[c.symbol] ? "fl-up" : "fl-down") : "");
    // the 24-hour change against the close 96 bars ago (the server's chg24 is of the last close)
    const chg = (c) => (now[c.symbol] && ok(c.chg24) && ok(c.last) ? now[c.symbol].px / (Number(c.last) / (1 + Number(c.chg24))) - 1 : c.chg24);
    const live = Object.values(now).some((q) => q.src === "live");
    pxSrc.textContent = live ? "가격 · 바이낸스 마크 · 5초마다" : "가격 · 끝난 15분봉 (지금 가격 못 받음)";
    put(prices, (d.coins || []).map((c) => h("button", {type: "button", class: ["dk-pr", st.sel === c.symbol ? "on" : "", fl(c)],
      title: now[c.symbol] && now[c.symbol].src === "live" ? "지금 가격 (바이낸스 마크)" : c.ko || "끝난 15분봉 종가",
      onclick: () => { st.sel = c.symbol; st.wipe = true; draw(); }},
      h("small", {class: "dk-mono"}, c.coin), h("b", {class: "num"}, now[c.symbol] ? pxKo(now[c.symbol].px) : "—"),
      h("small", {class: ["num", ok(chg(c)) ? (chg(c) >= 0 ? "up" : "down") : ""]}, c.state === "ok" ? pctKo(chg(c)) : c.ko || "못 읽음"))));
    const tp = (d.tape || []).slice(0, 14);
    const txt = tp.length ? tp.map((r) => `${fmt.hm(r.ts)} ${r.bot_ko} ${r.coin || ""} ${r.kind_ko}: ${r.text}`).join("   ◆   ") : "아직 봇 기록이 없어요 · 봇이 켜지면 신호와 거래가 여기 흘러요";
    put(tickIn, h("span", null, txt), h("span", {"aria-hidden": "true"}, `   ◆   ${txt}`));
    const T = d.totals || {};
    const ft = [`총 잔고 ${ok(T.equity) ? fmt.usd(T.equity) : "—"}`, `시작 대비 ${ok(T.pnl) ? `${T.pnl >= 0 ? "+" : ""}${fmt.usd(T.pnl)}` : "—"}`,
      `오늘 손익 ${ok(T.today_pnl) ? `${T.today_pnl >= 0 ? "+" : ""}${fmt.usd(T.today_pnl)}` : "—"}`, `열린 포지션 ${fmt.int(T.open || 0)}개`,
      `닫힌 거래 ${fmt.int(T.n || 0)}번`, `승률 ${ok(T.win_rate) ? pctKo(T.win_rate, 1).replace("+", "") : "—"}`,
      `48시간 신호 ${fmt.int((d.flow || []).reduce((a, x) => a + x[1], 0))}번`, `진입 ${fmt.int((d.flow || []).reduce((a, x) => a + x[2], 0))}번`];
    const ftx = ft.join("   ·   ");
    put(footIn, h("span", null, ftx), h("span", {"aria-hidden": "true"}, `   ·   ${ftx}`));
  }

  const tile = (k, v, cls) => h("div", {class: "dk-wt"}, h("small", {class: "dk-mono"}, k), h("b", {class: ["num", cls || ""]}, v));
  function drawWallet(d) {
    const T = d.totals || {};
    eqLed.className = ["dk-led", "num", ok(T.pnl) ? (T.pnl >= 0 ? "up" : "down") : ""].filter(Boolean).join(" ");
    motion.countTo(eqLed, ok(T.equity) ? Number(T.equity) : null, {format: (v) => fmt.usd(v), flash: true});
    const bots = d.bots || [];
    const curve = bots.map((b) => pctCurve(b.curve)).filter((c) => c.length > 1).sort((a, b) => b.length - a.length)[0] || [];
    const run = bots.filter((b) => (b.status || {}).state === "running").length;
    put(wallet,
      h("small", {class: "dk-mono"}, "ALL BOTS · EQUITY"),
      eqLed,
      h("p", {class: "dk-wsub"}, ok(T.equity) ? `실거래 봇 ${fmt.int(T.bots)}개 잔고 합 (마지막으로 읽은 값)` : "아직 실거래 잔고 기록이 없어요 · 봇이 켜질 때 처음 읽어요"),
      h("div", {class: "dk-wst"},
        tile("시작 대비", ok(T.pnl) ? `${T.pnl >= 0 ? "+" : ""}${fmt.usd(T.pnl)}` : "—", ok(T.pnl) ? (T.pnl >= 0 ? "up" : "down") : ""),
        tile("오늘 손익", ok(T.today_pnl) ? `${T.today_pnl >= 0 ? "+" : ""}${fmt.usd(T.today_pnl)}` : "—", ok(T.today_pnl) ? (T.today_pnl >= 0 ? "up" : "down") : ""),
        tile("닫힌 거래", `${fmt.int(T.n || 0)}번`),
        tile("승률", ok(T.win_rate) ? pctKo(T.win_rate, 1).replace("+", "") : "—"),
        tile("열린 포지션", `${fmt.int(T.open || 0)} / 3`, T.open ? "warn" : ""),
        (() => { const u = risksOf(d).map((x) => x.r && x.r.pnl).filter(ok);
          const sum = u.length ? u.reduce((a, v) => a + v, 0) : null;
          return tile("미실현 · 수수료 전", sum == null ? (T.open ? "—" : "$0.00") : usdKo(sum), ok(sum) && sum !== 0 ? (sum > 0 ? "up" : "down") : ""); })()),
      h("span", {class: "dk-chip"}, `실거래 봇 ${run}/3 돌고 있음`),
      h("div", {class: "dk-wcurve"}, h("small", {class: "dk-mono"}, "EQUITY · 시작 대비 %"),
        curve.length > 1 ? spark(curve.map((p) => p[1]), curve[curve.length - 1][1] >= 0 ? "up" : "down", 240, 48) : h("small", {class: "dk-ps"}, "거래가 쌓이면 선이 그려져요")));
  }

  function drawChart(d) {
    const sel = st.sel;
    put(coinTabs, (d.coins || []).map((c) => h("button", {type: "button", role: "tab", "aria-selected": c.symbol === sel ? "true" : "false",
      class: ["dk-ctab", c.symbol === sel ? "on" : "", toneOf(c.trend30 && c.trend30.length ? c.trend30[c.trend30.length - 1][1] : null)],
      onclick: () => { st.sel = c.symbol; st.wipe = true; draw(); }}, c.coin)));
    const c = coinOf(sel);
    if (!c || c.state !== "ok") { put(chart, ui.empty(c ? `${c.coin}: ${c.ko || "못 읽음"}` : "코인 값을 읽는 중")); chartSub.textContent = ""; return; }
    const t = c.tm30 || {};
    const marks = c.hist_rule === "o4h" ? "▲▼ OBV 히스토그램 전환(▲ 0선 아래 양봉 · ▼ 0선 위 음봉, 두 봇 진입)"
      : "▲▼ 3합 히스토그램 0선 돌파 · ○ OBV 히스토그램 전환";
    chartSub.textContent = `${c.coin} 15분봉 · ${marks} · 아래 띠 = 30분 ${TM_KO} (지금 ${tmKo(c)}${t.yellow ? " · 노란 막대" : ""})`;
    put(chart, chartSvg(c, holdsOf(sel), wOf(chart)));
  }

  function drawBots(d) {
    put(botsBox, (d.bots || []).map((b) => {
      const sta = (b.status || {}).state || "off";
      const p = b.position, pp = b.paper || {}, r = b.record || {};
      return h("article", {class: ["dk-bot", sta]},
        h("div", {class: "dk-brow"}, h("i", {class: ["dk-ledd", sta], "aria-hidden": "true"}),
          h("b", null, b.name_ko), h("small", {class: "dk-mono"}, `${b.account_ko} · ${sta === "running" ? "돌고 있음" : sta === "off" ? "꺼짐" : sta === "stopped" ? "멈춤" : "확인 필요"}`)),
        h("small", {class: "dk-ps"}, `${b.tf_ko || "—"}봉 진입 · ${TM_KO} ${b.trend_tf_ko || b.tf_ko || "—"} · ${(b.rules_ko || []).join(" + ") || "—"}`),
        h("dl", {class: "dk-kv dk-kv3"},
          h("dt", null, "잔고"), h("dd", {class: "num"}, ok((b.equity || {}).value) ? fmt.usd(b.equity.value) : "—"),
          h("dt", null, "거래"), h("dd", {class: "num"}, `${fmt.int(r.n || 0)}번${ok(r.win_rate) ? ` · ${pctKo(r.win_rate, 0).replace("+", "")}` : ""}`),
          h("dt", null, "모의"), h("dd", {class: "num"}, ok(pp.equity) ? `${fmt.usd(pp.equity)}${b.parity && ok(b.parity.share) ? ` · 같은 진입 ${pctKo(b.parity.share, 0).replace("+", "")}` : ""}` : "—")),
        p && p.state === "ok" ? h("p", {class: ["dk-bpos", p.side > 0 ? "up" : "down"]}, `${p.coin} ${p.side_ko} · 진입 ${pxKo(p.entry)} · 손절 ${pxKo(p.stop)}${p.step ? ` · 계단 ${p.step}단계` : ""}`)
          : h("p", {class: "dk-bpos"}, sta === "off" ? "아직 꺼져 있어요" : "포지션 없음 · 신호 기다리는 중"));
    }));
  }

  function drawGrid(d) {
    const bots = d.bots || [], rows = d.grid || [];
    put(gridBox, h("div", {class: "dk-gh"}, h("span"), ...rows.map((row) => h("small", {class: "dk-mono"}, row.coin))),
      ...bots.map((b) => h("div", {class: "dk-gr"},
        h("b", {class: "dk-gbot"}, h("i", {class: ["dk-ledd", (b.status || {}).state || "off"], "aria-hidden": "true"}), b.name_ko),
        ...rows.map((row) => {
          const c = (row.bots || {})[b.id], x = cellOf(c);
          return h("div", {class: ["dk-cell", x.tone, x.sig ? "sig" : ""], title: c ? `${b.name_ko} ${row.coin}: ${c.why || x.sub}` : `${b.name_ko}: 기록 없음`},
            h("b", {class: "num"}, x.big), h("small", null, x.sub),
            c && ok(c.close_ms) ? h("small", {class: "dk-mono"}, fmt.hm(c.close_ms)) : null);
        }))));
  }

  function drawCard(d) {
    const c = cardOf(d.bots, d.mmr);
    if (!c) { cardSub.textContent = "봇의 진입이 생기면 여기 카드가 떠요"; put(cardBox, ui.empty("아직 진입한 적이 없어요")); return; }
    cardSub.textContent = c.live ? "지금 열린 포지션" : "지난 진입 · 지금 포지션 없음";
    const tone = c.side > 0 ? "up" : "down";
    put(cardBox, h("article", {class: ["dk-card", tone, c.live ? "live" : "past"]},
      h("header", {class: "dk-cdh"}, h("b", null, `${c.coin} · ${c.bot}`), h("small", {class: "dk-mono"}, `${c.lev ? `${c.lev}배` : ""} · ${fmt.kst(c.ts)}${c.live ? "" : " · 지난 진입"}`)),
      h("div", {class: ["dk-side", tone]}, h("b", null, c.sideKo), h("span", null, c.sideEn),
        c.tm !== undefined ? h("div", {class: "dk-agree"}, h("span", null, `${TM_KO} 30분 히스토그램`),
          h("b", {class: "num"}, c.tm !== null ? fmt.num(c.tm, 2, true) : "—"),
          h("i", {class: "dk-agbar"}, h("i", {style: {width: c.tm !== null && Math.sign(c.tm) === c.side ? "100%" : "0%"}})))
          : h("div", {class: "dk-agree"}, h("span", null, "추세 바 30분 같은 쪽"), h("b", {class: "num"}, ok(c.agree) ? `${c.agree} / 6` : "—"),
            h("i", {class: "dk-agbar"}, h("i", {style: {width: `${ok(c.agree) ? (c.agree / 6) * 100 : 0}%`}})))),
      c.live ? cardNow : null,
      h("div", {class: "dk-crow entry"}, h("b", null, "진입"), h("p", null, `${pxKo(c.entry)} · ${c.why || "신호 기록 없음"}`)),
      h("div", {class: "dk-crow stop"}, h("b", null, "손절"),
        h("p", null, `${pxKo(c.stop)}${ok(c.dist) ? ` (진입에서 ${fmt.num(c.dist * 100, 2)}%)` : ""} · 진입 봉 ATR(14) × ${c.stopAtr ? fmt.num(c.stopAtr, 0) : "?"} · 거래소에 걸어 둔 손절`)),
      h("div", {class: "dk-crow target"}, h("b", null, "목표"),
        h("p", null, `${c.target}${ok(c.act) ? ` · 첫 계단 가격 약 ${pxKo(c.act)}` : ""}${c.step ? ` · 지금 ${c.step}단계 잠금` : ""}`)),
      h("div", {class: "dk-cstats"},
        h("div", null, h("small", null, "손익비 (첫 계단 : 손절)"), h("b", {class: "num"}, ok(c.rr) ? `1 : ${fmt.num(c.rr, 2)}` : "—")),
        h("div", null, h("small", null, "레버리지"), h("b", {class: "num"}, c.lev ? `${c.lev}x` : "—")),
        h("div", null, h("small", null, "예상 청산가 (대략)"), h("b", {class: "num down"}, ok(c.liq) ? pxKo(c.liq) : "—")))));
    drawCardNow(d);
  }

  function drawLife(d) {
    put(lifeBox, (d.bots || []).map((b) => {
      const p = b.position;
      const c = p && p.state === "ok" ? coinOf(p.symbol) : null;
      const q = c ? pn(c) : null;
      const ln = laneOf(p, q ? q.px : null);
      if (!ln) {
        return h("div", {class: "dk-lane idle"}, h("b", null, b.name_ko),
          h("div", {class: "dk-track"}, h("span", {class: "dk-trackline"})),
          h("small", {class: "dk-ps"}, (b.status || {}).state === "off" ? "꺼짐" : ["대기 · 다음 15분 마감까지 ", h("b", {class: "num", "data-wait": "1"}, "--:--")]));
      }
      const mk = (x, cls, ko) => (x == null ? null : h("i", {class: ["dk-mk", cls], style: {left: `${(x * 100).toFixed(1)}%`}, title: ko}));
      return h("div", {class: ["dk-lane", p.side > 0 ? "long" : "short"]}, h("b", null, `${b.name_ko} · ${p.coin} ${p.side_ko}`),
        h("div", {class: "dk-track"}, h("span", {class: "dk-trackline"}),
          ln.stop != null && ln.entry != null ? h("span", {class: "dk-risk", style: {left: `${Math.min(ln.stop, ln.entry) * 100}%`, width: `${Math.abs(ln.entry - ln.stop) * 100}%`}}) : null,
          ln.entry != null && ln.next != null ? h("span", {class: "dk-gain", style: {left: `${Math.min(ln.entry, ln.next) * 100}%`, width: `${Math.abs(ln.next - ln.entry) * 100}%`}}) : null,
          mk(ln.stop, "stop", `손절 ${pxKo(p.stop)}`), mk(ln.entry, "entry", `진입 ${pxKo(p.entry)}`), mk(ln.next, "next", `다음 계단 ${pxKo(ln.nextPx)}`), mk(ln.now, "now", "지금 가격")),
        h("small", {class: "dk-ps"}, `손절 ${pxKo(p.stop)} · 진입 ${pxKo(p.entry)} · 다음 계단 ${pxKo(ln.nextPx)}${ok(ln.roe) ? ` · 지금 ROE ${pctKo(ln.roe, 1)}` : ""}${p.step ? ` · ${p.step}단계 잠금` : ""}`));
    }));
  }

  function drawCore(d) {
    const coins = d.coins || [];
    const hold = ((d.bots || []).find((b) => b.position && b.position.state === "ok") || {}).position;
    const hot = (coins.find((c) => (c.cross || []).length && c.cross[c.cross.length - 1]) || {}).symbol || null;
    const sc = coinOf(st.sel);
    const lastH = sc ? (sc.hist || []).filter(ok).slice(-1)[0] : null, lastX = sc ? (sc.cross || []).slice(-1)[0] : 0;
    const tm30 = (sc && sc.tm30) || null, rg = sc && sc.trend30 && sc.trend30.length ? toneOf(sc.trend30[sc.trend30.length - 1][1]) : "na";
    const nc = nextClose(serverNow());
    const tr = [];
    for (const b of d.bots || []) for (const t of b.trades || []) tr.push({...t, bot: b.name_ko});
    tr.sort((a, b) => (b.exit_ms || 0) - (a.exit_ms || 0));
    const late = tr.slice(0, 7);
    core.set(coins.map((c) => ({sym: c.symbol, tone: c.state === "ok" && c.trend30 && c.trend30.length ? toneOf(c.trend30[c.trend30.length - 1][1]) : "na"})),
      hot, hold ? hold.symbol : null, [
        {k: `PROBE · ${sc ? sc.coin : "—"} 15M ${sc && sc.hist_rule === "o4h" ? "OBV" : "3합"}`, v: ok(lastH) ? fmt.num(lastH, 2) : "—", tone: ok(lastH) ? (lastH >= 0 ? "up" : "down") : "",
          s: lastX ? `방금 ${markKo(sc, lastX)}` : (sc && sc.hist_rule === "o4h" ? "이번 봉 전환 없음" : "이번 봉 0선 돌파 없음")},
        {k: "REGIME · 30M 추세 MACD", v: rg === "flat" ? "0선" : TREND_KO[rg], tone: rg,
          s: tm30 && ok(tm30.hist) ? `히스토그램 ${fmt.num(tm30.hist, 2, true)}${tm30.yellow ? " · 노란 막대" : ""}` : ""},
        {k: "NEXT CLOSE · 15M", v: mmss(nc.left_ms), s: `${fmt.hm(nc.at)} 마감 · 봇들이 판단해요`}],
      late.map((t) => (t.win ? "up" : t.win === false ? "down" : "na")));
    put(inputs, coins.map((c, k) => {
      const tone = c.state === "ok" && c.trend30 && c.trend30.length ? toneOf(c.trend30[c.trend30.length - 1][1]) : "na";
      return h("div", {class: ["dk-in", tone]}, h("div", {class: "dk-inh"}, h("b", {class: ["dk-mono", "dk-cid", CID(k)]}, `${c.coin} · 15M`),
        h("small", {class: ["num", ok(c.chg24) ? (c.chg24 >= 0 ? "up" : "down") : ""]}, c.state === "ok" ? pctKo(c.chg24) : "—")),
      c.state === "ok" ? spark(c.spark, `dk-cid ${CID(k)}`, 160, 30) : h("small", {class: "dk-ps"}, c.ko || "못 읽음"));
    }));
    put(fills, h("small", {class: "dk-mono"}, "LATE FILLS · 최근 청산"),
      late.length ? late.map((t) => h("div", {class: ["dk-fill", t.win ? "up" : t.win === false ? "down" : ""]},
        h("b", null, `${t.coin} ${t.side > 0 ? "롱" : "숏"}`), h("small", null, `${t.bot} · ${t.why_ko || ""}`),
        h("b", {class: "num"}, ok(t.pnl) ? `${t.pnl >= 0 ? "+" : ""}${fmt.usd(t.pnl)}` : "모름"), h("small", {class: "dk-mono"}, fmt.kst(t.exit_ms))))
        : h("small", {class: "dk-ps"}, "아직 청산한 거래가 없어요"));
  }

  const keyOf = (r) => `${r.ts}|${r.bot_ko}|${r.kind}|${r.text}`;
  function drawTape(d) {
    const rows = (d.tape || []).slice(0, 18);
    const seen = st.seen || null;                      // (the first read marks nothing new)
    st.seen = new Set(rows.map(keyOf));
    const fresh = seen ? rows.filter((r) => !seen.has(keyOf(r)) && ["entry", "adopted", "exit"].includes(r.kind)) : [];
    if (fresh.length) {                                // owners 11-01: an entry or an exit of the three bots sounds and shows
      try { sound.playLive(liveSoundsOf(fresh)); } catch (e) { /* no sound here: the toast still shows */ }
      const r = fresh[0];
      toast.className = ["dk-toast", r.kind === "exit" ? (ok(r.pnl) && r.pnl > 0 ? "up" : "down") : "entry"].join(" ");
      put(toast, h("b", null, `● ${r.bot_ko} · ${r.coin || ""} ${r.kind_ko}`), h("span", null, r.text || ""),
        ok(r.pnl) ? h("b", {class: "num"}, usdKo(r.pnl)) : null);
      toast.hidden = false;
      if (typeof ctx.timeout === "function") ctx.timeout(() => { toast.hidden = true; }, 9000);
    }
    put(tape, rows.length ? h("div", {class: "dk-tscroll"}, h("table", {class: "dk-ttab"},
      h("thead", null, h("tr", null, ...["시각", "봇", "코인", "종류", "내용", "손익"].map((x) => h("th", null, x)))),
      h("tbody", null, rows.map((r) => h("tr", {class: [r.kind, r.side > 0 ? "long" : r.side < 0 ? "short" : "", seen && !seen.has(keyOf(r)) ? "new" : ""]},
        h("td", {class: "num"}, fmt.kst(r.ts)), h("td", null, r.bot_ko), h("td", null, r.coin || "—"),
        h("td", null, h("span", {class: ["dk-kind", r.kind]}, r.kind_ko)), h("td", {class: "dk-ttext"}, r.text),
        h("td", {class: ["num", ok(r.pnl) ? (r.pnl >= 0 ? "up" : "down") : ""]}, ok(r.pnl) ? `${r.pnl >= 0 ? "+" : ""}${fmt.usd(r.pnl)}` : ""))))))
      : ui.empty("아직 기록이 없어요 · 봇이 켜지면 신호와 거래가 여기 쌓여요"));
  }

  function drawGoal(d) {
    const g = d.goal;
    if (!g || g.state === "error") { goalSub.textContent = ""; put(goalBox, ui.empty((g && g.ko) || "목표 숫자를 못 읽었어요")); return; }
    const T = Number(g.target) || 6, n = Number(g.month_days) || 30, a = g.all;
    goalSub.textContent = `${g.goal_ko} · ${fmt.kst(g.from_ms)}부터 · 기록으로 한 계산이지 예측이 아니에요`;
    const head = a ? h("div", {class: "dk-ghead"},
      h("div", {class: "dk-gbig"}, h("small", {class: "dk-mono"}, "봇 합 · 이번 달"),
        gMult,
        h("small", null, `오늘 목표 경로 ${multKo(a.path_now)} · 경로보다 ${pctKo(a.vs_path, 1)}`)),
      h("div", {class: "dk-gbig"}, h("small", {class: "dk-mono"}, "남은 날 하루에 필요"),
        gNeed,
        h("small", null, `${fmt.num(Math.max(0, n - a.days), 1)}일 남음 · ×${fmt.num(T, 0)}까지 매일`)))
      : h("p", {class: "dk-ps"}, "이번 달 닫힌 거래가 아직 없어 목표 경로와 견줄 숫자가 없어요 (첫 거래부터 계산해요)");
    const rows = (g.bots || []).map((x) => {
      const k = (d.bots || []).findIndex((b) => b.id === x.id);
      const link = h("a", {class: "dk-glink", href: `#/${BOT_TAB[x.id] || "deck"}`}, "목표 연구 →");
      if (x.state !== "ok") return h("div", {class: ["dk-grow", "off"]}, h("b", null, x.name_ko), h("small", {class: "dk-ps"}, x.reason_ko || "기록이 없어요"), link);
      const m = x.month;
      const facts = [m && ok(x.need_daily) ? `남은 날 하루 ${pctKo(x.need_daily, 1)} 필요` : null,
        ok(x.pace_mult) ? `지금 속도면 30일 ${multKo(x.pace_mult)} (가상)` : null,
        ok(x.need_win) ? (Number(x.need_win) > 1 ? "지금 평균 이익·손실로는 승률 100%여도 모자라요" : `필요 승률 ${rateKo(x.need_win)}`) : null,
        ok(x.win_rate) ? `지금 승률 ${rateKo(x.win_rate)}` : null,
        ok(x.n) ? `닫힌 거래 ${fmt.int(x.n)}번` : null].filter(Boolean);
      return h("div", {class: ["dk-grow", x.tone ? `g-${x.tone}` : ""]},      // (g-: ".dk .warn" would paint the whole row)
        h("div", {class: "dk-gr1"}, h("span", {class: ["dk-legi", `b${k}`]}, h("i"), h("b", null, x.name_ko)),
          h("b", {class: ["num", m ? (m.vs_path >= 0 ? "up" : "down") : ""]}, m ? `${multKo(m.mult)} · 경로보다 ${pctKo(m.vs_path, 1)}` : "이번 달 거래 없음")),
        h("small", {class: "dk-mono"}, facts.length ? facts.join(" · ") : "—"),
        x.verdict_ko ? h("small", {class: ["dk-gv", x.tone || ""]}, x.verdict_ko) : null, link);
    });
    if (a) {
      gMult.className = ["num", a.vs_path >= 0 ? "up" : "down"].join(" ");
      motion.countTo(gMult, ok(a.mult) ? Number(a.mult) : null, {format: (v) => multKo(v)});
      motion.countTo(gNeed, ok(a.need_daily) ? Number(a.need_daily) : null, {format: (v) => pctKo(v, 1)});
    }
    // the owners' goals side by side (11-01: "700달러, 800달러 … 5000달러 그이상"): what each needs a day, arithmetic only
    const lad = h("div", {class: "dk-gladder"}, h("small", {class: "dk-mono"}, `목표별 하루 필요 · ${fmt.num(n, 0)}일 복리 · $100 시작 · 계산일 뿐 (예측 아님)`),
      h("div", {class: "dk-glrow"}, ladderOf(GOAL_LADDER, n).map((r) => h("div", {class: ["dk-gl", r.x === T ? "on" : ""]},
        h("b", {class: "num"}, `×${fmt.num(r.x, 0)}`), h("small", {class: "num"}, `$${fmt.int(r.usd)}`), h("small", {class: "num"}, `하루 ${pctKo(r.daily, 1)}`)))));
    put(goalBox, head, lad, goalSvg(g, d.bots, wOf(goalBox)), h("div", {class: "dk-grows"}, rows));
  }

  function drawFwd(d) {
    const bots = d.bots || [];
    const splits = bots.map((b) => b.rules_since_ms).filter(ok).map(Number);
    const split = splits.length ? Math.min(...splits) : null;
    const g = fwdSvg(bots, split, wOf(fwd));
    const stat = bots.map((b) => ({b, x: since(b.curve, split)})).filter((x) => x.x);
    const rets = stat.map((x) => x.x.ret), dds = stat.map((x) => x.x.dd);
    const par = bots.map((b) => b.parity).filter((p) => p && p.n);
    const pn = par.reduce((a, p) => a + p.n, 0), ps = par.reduce((a, p) => a + p.same, 0);
    put(fwd, g ? [g, h("div", {class: "dk-leg"}, bots.filter((b) => pctCurve(b.curve).length > 1).map((b, k) => h("span", {class: ["dk-legi", `b${k}`]}, h("i"), b.name_ko)))]
      : ui.empty("아직 거래가 없어 선이 없어요 · 청산할 때마다 잔고가 찍혀요"),
      h("div", {class: "dk-stats"},
        h("div", {class: "dk-stat"}, h("b", {class: ["num", rets.length ? (Math.min(...rets) >= 0 ? "up" : "down") : ""]}, rets.length ? rets.map((r) => pctKo(r, 1)).join(" / ") : "—"),
          h("small", {class: "dk-mono"}, split ? "새 규칙 뒤 수익" : "시작 뒤 수익")),
        h("div", {class: "dk-stat"}, h("b", {class: ["num", dds.length && Math.min(...dds) < 0 ? "down" : ""]}, dds.length ? pctKo(Math.min(...dds), 1) : "—"),
          h("small", {class: "dk-mono"}, "가장 깊은 낙폭")),
        h("div", {class: "dk-stat"}, h("b", {class: "num"}, pn ? `${fmt.int(ps)}/${fmt.int(pn)}` : "—"), h("small", {class: "dk-mono"}, "실거래 = 모의 진입"))));
  }

  const pn = (c) => priceNow(st.live, st.liveAt, c, Date.now());
  /** Each bot with an open position: {b, q (its price now), r (riskOf)}. */
  const risksOf = (d) => (d.bots || []).filter((b) => b.position && b.position.state === "ok").map((b) => {
    const c = coinOf(b.position.symbol), q = c ? pn(c) : null;
    return {b, q, r: q ? riskOf(b.position, q.px, (b.equity || {}).value, d.mmr, q.funding) : null};
  });
  function drawCardNow(d) {
    const x = risksOf(d)[0];
    if (!x || !x.r) { cardNow.className = "dk-crow now"; put(cardNow, h("b", null, "지금"), h("p", null, "지금 가격을 아직 못 받았어요")); return; }
    cardNow.className = ["dk-crow", "now", ok(x.r.pnl) ? (x.r.pnl >= 0 ? "up" : "down") : ""].filter(Boolean).join(" ");
    put(cardNow, h("b", null, "지금"), h("p", {class: "num"}, `${pxKo(x.r.px)} · ROE ${pctKo(x.r.roe, 1)} · ${usdKo(x.r.pnl)} (수수료 전)`,
      x.q.src === "live" ? "" : " · 끝난 15분봉 값"));
  }
  function drawRisk(d) {
    const pos = risksOf(d).filter((x) => x.r).map(({b, q, r}) => {
      const p = b.position, bar = riskBar(p, r);
      const mk = (v, cls, ko) => (v == null ? null : h("i", {class: ["dk-rmk", cls], style: {left: `${(v * 100).toFixed(1)}%`}, title: ko}));
      return h("article", {class: ["dk-rk", Number(p.side) > 0 ? "long" : "short", ok(r.toLiq) && r.toLiq < 0.03 ? "hot" : ""]},
        h("div", {class: "dk-rk1"}, h("b", null, `${b.name_ko} · ${p.coin} ${p.side_ko}`),
          h("small", {class: "dk-mono"}, `${p.leverage ? `${p.leverage}배 · ` : ""}지금 ${pxKo(r.px)}${q.src === "live" ? "" : " (15분봉)"}`)),
        bar ? h("div", {class: "dk-rbar", role: "img", "aria-label": "청산가 · 손절 · 진입 · 지금 가격"}, h("span", {class: "dk-rfill", style: {width: `${((bar.now || 0) * 100).toFixed(1)}%`}}),
          mk(bar.liq, "liq", `청산가 ${pxKo(r.liq)}`), mk(bar.stop, "stop", `손절 ${pxKo(p.stop)}`), mk(bar.entry, "entry", `진입 ${pxKo(p.entry)}`), mk(bar.now, "now", `지금 ${pxKo(r.px)}`)) : null,
        h("dl", {class: "dk-kv dk-kv3"},
          h("dt", null, "청산가까지"), h("dd", {class: ["num", ok(r.toLiq) && r.toLiq < 0.03 ? "down" : ""]}, ok(r.toLiq) ? `${fmt.num(r.toLiq * 100, 2)}% · ${pxKo(r.liq)} (대략)` : "—"),
          h("dt", null, "손절가까지"), h("dd", {class: "num"}, ok(r.toStop) ? `${fmt.num(r.toStop * 100, 2)}% · ${pxKo(p.stop)}` : "—"),
          h("dt", null, "손절가에 닿으면"), h("dd", {class: ["num", ok(r.stopPnl) ? (r.stopPnl >= 0 ? "up" : "down") : ""]},
            ok(r.stopPnl) ? `${usdKo(r.stopPnl)}${ok(r.stopPct) ? ` · 잔고의 ${pctKo(r.stopPct, 1)}` : ""} (수수료 전)` : "—"),
          h("dt", null, "펀딩 (바이낸스)"), h("dd", {class: ["num", r.funding ? (r.funding.pays ? "down" : "up") : ""]},
            r.funding ? `${pctKo(r.funding.rate, 4)} · ${r.funding.pays ? "이 포지션이 내요" : "이 포지션이 받아요"}${ok(r.funding.usd) ? ` · 한 번 ${usdKo(r.funding.usd)}` : ""}${ok(q.next_ms) ? ` · 다음 ${fmt.hm(q.next_ms)}` : ""}` : "지금 값 없음")));
    });
    const m = d.month && d.month.state !== "error" && d.month.days ? d.month : null;
    const month = m ? h("div", {class: "dk-rkm"},
      tile("이번 달 가장 깊은 낙폭", m.dd ? `${pctKo(m.dd.pct, 1)} · ${m.dd.bot_ko}` : "—", m.dd && m.dd.pct < 0 ? "down" : ""),
      tile("연속 손실 (지금 · 이번 달 최대)", `${fmt.int(m.loss_run || 0)}번 · ${fmt.int(m.max_loss_run || 0)}번`, m.loss_run >= 3 ? "warn" : ""),
      tile("이번 달 가장 큰 손실", m.worst_trade && m.worst_trade.pnl < 0 ? `${usdKo(m.worst_trade.pnl)} · ${m.worst_trade.coin || ""} ${m.worst_trade.bot_ko || ""}`
        : m.trades_n ? "손실 거래 없음" : "—", m.worst_trade && m.worst_trade.pnl < 0 ? "down" : ""),
      tile("이번 달 닫힌 거래", `${fmt.int(m.trades_n || 0)}번`)) : null;
    put(riskBox, pos.length ? pos : h("p", {class: "dk-rnone"}, "열린 포지션 없음 · 지금 걸려 있는 돈 없음"), month,
      h("small", {class: "dk-ps"}, "청산가는 격리 증거금 기준 대략값 · 펀딩은 바이낸스 값(거래소마다 조금 달라요) · 수수료 전"));
  }
  function drawCal(d) {
    const m = d.month;
    if (!m || m.state === "error" || !m.days) { calSub.textContent = ""; put(calBox, ui.empty((m && m.ko) || "이번 달 기록을 읽는 중")); return; }
    calSub.textContent = `봇 합 하루 손익 ÷ 그날 시작 잔고 · ×${fmt.num(m.target, 0)} 하려면 매일 ${pctKo(m.need, 1)} · 한국 시간`;
    const dow0 = (new Date(Number(m.from_ms) + 9 * 3600000).getUTCDay() + 6) % 7;          // Monday first
    const cells = [];
    for (let i = 0; i < dow0; i++) cells.push(h("i", {class: "dk-cd blank", "aria-hidden": "true"}));
    for (const x of m.days) {
      const has = x.state !== "future" && x.n;
      const tone = x.state === "future" ? "future" : !has ? "flat" : ok(x.pct) && x.pct >= m.need ? "over" : x.pnl > 0 ? "up" : x.pnl < 0 ? "down" : "flat";
      cells.push(h("div", {class: ["dk-cd", tone, x.state === "today" ? "today" : ""],
        title: has ? `${x.d}일 · 거래 ${x.n}번 · ${usdKo(x.pnl)}${ok(x.pct) ? ` · ${pctKo(x.pct, 2)}` : ""}` : `${x.d}일`},
        h("small", {class: "num"}, String(x.d)),
        x.state === "future" ? null : h("b", {class: "num"}, has ? (ok(x.pct) ? pctKo(x.pct, 1) : usdKo(x.pnl)) : "—"),
        has ? h("small", {class: "dk-mono"}, `${x.n}번${ok(x.pct) && x.pct >= m.need ? " ✓" : ""}`) : null));
    }
    put(calBox, h("div", {class: "dk-calh"}, ...["월", "화", "수", "목", "금", "토", "일"].map((w) => h("small", {class: "dk-mono"}, w))),
      h("div", {class: "dk-cal"}, cells),
      h("div", {class: "dk-calsum"}, tile("목표 넘은 날", `${fmt.int(m.over || 0)}일`, m.over ? "up" : ""),
        tile("번 날 · 잃은 날", `${fmt.int(m.green || 0)} · ${fmt.int(m.red || 0)}`),
        tile("가장 좋은 날", m.best ? `${m.best.d}일 ${pctKo(m.best.pct, 1)}` : "—", m.best && m.best.pct > 0 ? "up" : ""),
        tile("가장 나쁜 날", m.worst ? `${m.worst.d}일 ${pctKo(m.worst.pct, 1)}` : "—", m.worst && m.worst.pct < 0 ? "down" : "")),
      h("small", {class: "dk-ps"}, "✓ = 그날 목표 경로(매일 같은 %)를 넘은 날 · 거래 없는 날은 — · 계산일 뿐 예측이 아니에요"));
  }
  /** Every PX_MS: the price now, and what moves with it (the prices, the wallet's P&L now, the card's 지금, the lanes, 위험). */
  async function loadPx() {
    let r;
    try { r = await ctx.api(PX_API); } catch (e) { return; }
    if (!ctx.alive() || !r || r.state !== "ok") return;
    st.live = r; st.liveAt = Date.now();
    const d = st.d;
    if (!d) return;
    drawTop(d); drawWallet(d); drawCardNow(d); drawLife(d); drawRisk(d);
  }
  function drawFeed(d) {
    put(feedBox, feedSvg(d.coins, wOf(feedBox)));
    const w = wireOf(d.tape);
    put(wire, w.length ? w.map((r) => h("div", {class: ["dk-wl", r.kind]}, h("span", {class: "dk-wtm num"}, r.t), " ", h("span", {class: "dk-wj"}, r.txt)))
      : h("small", {class: "dk-ps"}, "아직 봇 기록이 없어요"));
    const f = d.flow || [], sig = f.reduce((a, x) => a + (Number(x[1]) || 0), 0), ent = f.reduce((a, x) => a + (Number(x[2]) || 0), 0);
    const tr = (d.coins || []).filter((c) => c.state === "ok" && c.trend30 && c.trend30.length).map((c) => toneOf(c.trend30[c.trend30.length - 1][1]));
    const T = d.totals || {}, cnt = (t) => tr.filter((x) => x === t).length;
    const stat = (k, v, cls) => h("div", {class: "dk-fs"}, h("small", {class: "dk-mono"}, k), h("b", {class: ["num", cls || ""]}, v));
    put(feedStats, stat("신호 · 48H", `${fmt.int(sig)}번`), stat("진입 · 48H", `${fmt.int(ent)}번`, ent ? "up" : ""),
      stat("열린 포지션", `${fmt.int(T.open || 0)} / 3`, T.open ? "warn" : ""),
      stat(`30분 ${TM_KO}`, `▲${cnt("up")} ▼${cnt("down")}${cnt("flat") ? ` ■${cnt("flat")}` : ""}`),
      h("div", {class: "dk-fs"}, h("small", {class: "dk-mono"}, "다음 15분 마감"), h("b", {class: "num", "data-wait": "1"}, mmss(nextClose(serverNow()).left_ms))));
  }
  function drawHist(d) {
    const c = coinOf(st.sel);
    if (!c || c.state !== "ok") { put(hist, ui.empty("코인 값을 읽는 중")); histSub.textContent = ""; return; }
    const last = (c.hist || []).filter(ok).slice(-1)[0];
    histSub.textContent = c.hist_rule === "o4h"
      ? `${c.coin} 15분봉 OBV 히스토그램 (레인지 봇 · 친구 15분 봇 진입) · 0 위 초록 · 0 아래 빨강 · 점 = 전환(0선 아래 양봉 · 0선 위 음봉) · 지금 ${ok(last) ? fmt.num(last, 2) : "—"}`
      : `${c.coin} 15분봉 3합 히스토그램 (친구 15분 봇 진입) · 0 위 초록 · 0 아래 빨강 · 점 = 0선 돌파 · 지금 ${ok(last) ? fmt.num(last, 2) : "—"}`;
    put(hist, histSvg(c, wOf(hist)));
    put(flow, flowSvg(d.flow, wOf(flow)));
  }

  function draw() {
    const d = st.d;
    if (!d) return;
    if (!st.sel || !coinOf(st.sel)) {
      const held = (d.bots || []).find((b) => b.position && b.position.state === "ok");
      st.sel = held ? held.position.symbol : ((d.coins || [])[0] || {}).symbol || null;
    }
    drawTop(d); drawWallet(d); drawChart(d); drawFeed(d); drawBots(d); drawGrid(d); drawCard(d); drawRisk(d); drawGoal(d); drawCal(d); drawLife(d);
    drawCore(d); drawTape(d); drawFwd(d); drawHist(d);
    tickClock();
    if (st.wipe) {                                     // another coin picked: its charts draw in from the left
      st.wipe = false;
      for (const b of [chart, hist]) if (b.firstChild) motion.play(b.firstChild, "dk-wipe1");
    }
  }
  async function load() {
    if (st.busy) return;
    st.busy = true;
    let d;
    try { d = await ctx.api(DECK_API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (st.d) put(slot, ui.staleNote(e, st.okAt, () => load().catch(() => {})));
      else put(slot, ui.errorBox(e, () => load()));
      throw e;
    } finally { st.busy = false; }
    if (!ctx.alive()) return;
    put(slot);
    st.d = d; st.okAt = Date.now();
    draw();
  }
  put(gridBox, ui.empty("불러오는 중"));
  if (typeof ResizeObserver === "function") {             // the charts follow the panel's width (a turned phone, a resized window)
    let wLast = 0, tmr = 0;
    const ro = new ResizeObserver(() => {
      const w = Math.round(chart.getBoundingClientRect().width);
      if (Math.abs(w - wLast) < 8) return;
      wLast = w;
      clearTimeout(tmr);
      tmr = setTimeout(() => { if (ctx.alive()) draw(); }, 150);
    });
    ro.observe(chart);
    ctx.track(() => { ro.disconnect(); clearTimeout(tmr); });
  }
  if (typeof ctx.timeout === "function") ctx.timeout(() => el.classList.remove("boot"), 3200);   // (the opening is over)
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  ctx.every(1000, tickClock);
  ctx.every(PX_MS, () => loadPx().catch(() => {}));       // the price now (owners 11-01)
  return {el, set() {}};
}

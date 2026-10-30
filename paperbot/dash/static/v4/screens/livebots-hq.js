// 실거래 › 한눈에 (#/hq; 관제 and the first tab 10/19-10/21, now second after 추세판단 봇's 관제; owners 10/19: "좀 간지나는것도 좀 만들어주면 안돼?? 멋있게 만들고싶은데",
// with three phone videos of another team's dashboard as the look they like: a neon frame, mono-caps status line, hero
// wallet digits with DAY n and a × badge, a scrolling ticker, an entry card, an exchange-style result card and a
// rotating particle torus).
// The control room of the two real-money executors at a glance, view-only (no order button anywhere):
//   status    '● LIVE TRADE · DAY n · 바이비트 · MEXC' (LIVE only while an executor's record is fresh), the server's own answer
//             to "왜 지금 진입 안 하나" (/api/v4/livebots/now) as one headline, the Korea-time clock; a pause banner while
//             the bots rest (weekend / a US release, /now and /api/v4/livebots/calendar)
//   frame     the neon main panel: 바이비트 and MEXC as reactors (status LED, DAY n since that executor's live start, the
//             wallet as a hero number with × its first balance record, today's realized P&L, the signal light as a ring of
//             its 20 squares with its threshold, the account it follows) around the centre: the ring of strategies (a canvas
//             particle torus: one arc of points per strategy of the config, as long as its settings, brighter for this
//             week's signals, the position's strategy pulsing, a stream of particles to the coin on a real new signal or
//             entry; it turns only while the paper bot's record is fresh) over a gauge while a position is open (stop →
//             entry → next lock steps, the needle at the paper's net ROE at the live mark, the exchanges' stops on the same
//             scale) or the idle words (the pause, the waits, the last signal); under them '40번 판단까지 n/40' as a progress
//             bar and a slow ticker of the real numbers
//   cards     ⏳ 진입 대기 (the break signals still waiting: the level to cross, the last price, how far, the deadline; the
//             reason a wait cannot become an entry now; else the next bar closes), 진입 카드 (the open position: strategy, timeframe, setting, stop rule, entry / stop per account, the first lock
//             and the next ladder step, 손익비 첫 잠금 기준; no position: the last signal and what became of it), 결과 카드 (the
//             last closed live trade, else the paper's, labelled), 실시간 (the newest fills, alarms and the last signal)
//   below     the checklist of /now (✓ / ✕ / ? with live countdowns), today's 24 h dial (KST) with the pause windows and
//             today's entries (the 추세판단 봇's from its start only: started today, '새 봇 시작 HH:MM 뒤'), the 40-trade
//             checkpoint ring with the owners' rule (text only, nothing judged before 40),
//             the 27 strategies lit by this week's signals (/api/v4/livebots/rank), the one holding the position glowing
// The summary (/api/v4/livebots) comes from livebots.js (set(d, state) every 5 s; that screen dims the page with the
// answer's age when a refresh fails); /now, /calendar and /rank are polled here and each keeps its last answer, dimmed
// with its age, when a refresh fails.
// HONESTY: unreadable = 못 읽음 + why, not there yet = 수집 전, never a zero for what is unknown; every motion follows real
// state: the needle and the wallet move on a real new number, the ring turns only while the paper bot really runs, the
// LED breathes only while its record is fresh, the ticker shows only numbers the server sent, a celebration fires once per
// browser for a milestone that really happened while the page was watching (localStorage remembers it); nothing moves on a
// hidden page or under reduced motion.
// The geometry and the rules (ring segments, gauge angles, dial arcs, tile brightness, DAY n, ×, milestones, the cards'
// numbers, the countdown) are exported pure functions (tests/test_dash_livebots_hq.py runs them in node).
// The third executor (딥코인, owners 10/24) gets its own reactor, ticker item and gauge row while the server has it
// (livebots-kit.js execIds): the deck then puts the centre on top and the three reactors in a row; else as before.
// The four live accounts side by side (owners 10/25 night: the three ways of trading must never be mixed up): 바이비트 ·
// WOO X Pro (they follow 추세판단 봇) · 딥코인 (it follows VWAP 개선판; before its executor is installed a card that says
// 설치 전) · WOO X Pro 2 (친구 30분 봇(믹스), paperbot/mixchop.py: no paper bot, it trades by itself; its card from
// /api/v4/livebots/mix, dash/more/livemix.py: running or 꺼짐 / 기록 멈춤, the last equity it logged, its last 20 closed
// trades as the ring, today, the position, whether it may enter now). Every card says which bot it is or follows (봇 …)
// under the account's name; the old '친구 매매법' executor of WOO X Pro 2 keeps its own reactor while the server has it.
import {h, s, put, ui, fmt, motion, store, serverNow, local} from "../core/pb.js";
import {lightWords, lightCells, netRoe, roeAt, roePrice, liveToday, unrealized} from "./livebots-calc.js";
import {ACCT, paperBotKo, EXEC_SLOTS, execIds, execsNow, execsKo, isPaperId} from "./livebots-kit.js";
import {expectLines} from "./livebots-trend.js";
import {takingKo, takingNoneKo} from "./livebots-likely.js";

export const NOW_API = "/api/v4/livebots/now";
export const CAL_API = "/api/v4/livebots/calendar";
export const RANK_API = "/api/v4/livebots/rank";
export const MIX_API = "/api/v4/livebots/mix";
const NOW_MS = 15 * 1000, CAL_MS = 30 * 1000, RANK_MS = 30 * 1000, MIX_MS = 15 * 1000;
const MIX_BOT_KO = "친구 15분 봇";                    // the friend bot's name on 한눈에 (owners 10-30: ROC / OBV 50 on 15m bars)
export const MIXBYBIT_API = "/api/v4/livebots/mixbybit";
/** The mix bots' cards (paperbot/mixchop.py, each trading an account by itself): the account's slot (its colour and its
 *  place in the deck), its words, its answer, its screen; ``replaces``: shown only once the summary says it took that
 *  executor slot (owners 10-29: the 바이비트 봇 in the Bybit slot); ``oldExec``: the old executor of the same account. */
export const MIX_BOTS = [
  {slot: "wooxpro2", account: "WOO X Pro 2", exchange: "WOO X Pro 2", bot: MIX_BOT_KO, api: MIX_API, unit: "paperbot-mixchop",
    tab: "mix", linkKo: "믹스 관제 · 성적 →", oldExec: "wooxpro2", oldKo: "'친구 매매법'", replaces: null, cls: ""},
  {slot: "bybit", account: "바이비트", exchange: "바이비트", bot: "바이비트 봇", api: MIXBYBIT_API, unit: "paperbot-mixbybit",
    tab: "bybit", linkKo: "바이비트 봇 관제 · 성적 →", oldExec: "bybit", oldKo: "추세판단 봇을 따라가던", replaces: "bybit", cls: "lbh-mixb"},
];
export const COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"];
const DAY = 86400000, KST = 9 * 3600000;
const SPIN = 0.00011;                                // the ring's turn (rad / ms): about one turn in a minute
const FRAME_MS = 33;                                 // at most about 30 frames a second
const STREAM_MS = 2400;
const MAX_PX = 700000;                               // the ring's canvas at most this many pixels (devicePixelRatio lowered above it)                              // a stream of particles from a strategy's arc to a coin
// the coins' labels around the ring (% of the box): three on each side, the lines from the ring end at them
const COIN_AT = [[3, 18], [1, 50], [3, 82], [97, 18], [99, 50], [97, 82]];
const MS_KEY = "lbh-ms";                             // the milestones this browser has already seen (local, try/catch inside)
const RECENT_MS = 180000;                            // a first win this recent counts as 'now' on the first look

// ================================================================ pure functions (no DOM: node tests)
/** A point on a circle: deg 0 = up (12 o'clock), clockwise. */
export function polar(cx, cy, r, deg) {
  const t = (Number(deg) * Math.PI) / 180;
  return [cx + r * Math.sin(t), cy - r * Math.cos(t)];
}
/** An SVG arc path from a0 to a1 degrees (clockwise, 0 = up); a full turn is drawn as 359.99°. */
export function arcPath(cx, cy, r, a0, a1) {
  let b = Number(a1);
  const a = Number(a0);
  if (b - a >= 360) b = a + 359.99;
  if (b < a) b = a;
  const [x0, y0] = polar(cx, cy, r, a), [x1, y1] = polar(cx, cy, r, b);
  return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${r} ${r} 0 ${b - a > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

/** Seconds -> "07:05:09", a day or more "2일 07:05:09"; null / NaN -> "—"; never below zero. */
export function clockOf(sec) {
  if (sec == null || !Number.isFinite(Number(sec))) return "—";
  const t = Math.max(0, Math.floor(Number(sec)));
  const d = Math.floor(t / 86400), two = (n) => String(n).padStart(2, "0");
  const c = `${two(Math.floor((t % 86400) / 3600))}:${two(Math.floor((t % 3600) / 60))}:${two(t % 60)}`;
  return d ? `${d}일 ${c}` : c;
}

/** An account's status LED from the summary's accts row: {id: run | stale | halt | bad | none | wait, ko, why}. */
export function ledOf(a) {
  if (!a) return {id: "wait", ko: "불러오는 중", why: null};
  if (a.state === "missing" || a.state === "none") return {id: "none", ko: "수집 전", why: a.reason_ko || "아직 기록이 없어요"};
  if (a.state !== "ok") return {id: "bad", ko: "못 읽음", why: a.reason_ko || "기록을 읽지 못했어요"};
  if (a.halted) return {id: "halt", ko: "멈춤", why: a.halt_reason || "이유 기록 없음"};
  if (a.stale) return {id: "stale", ko: "기록 멈춤", why: a.kind === "paper" ? "페이퍼 봇은 1분마다 기록해요: 꺼져 있을 수 있어요" : "실행기는 몇 초마다 기록해요: 꺼져 있거나 멈췄을 수 있어요"};
  return {id: "run", ko: "돌아가는 중", why: null};
}

/** 00:00 KST of the day `ms` is in. */
export const kstDayStart = (ms) => Math.floor((Number(ms) + KST) / DAY) * DAY - KST;
/** DAY n of an executor: Korea-time days since its live start, the start day being DAY 1 (null without a start). */
export function dayN(since, now) {
  if (since == null || !(Number(since) > 0) || Number(since) > Number(now) + 60000) return null;
  return Math.round((kstDayStart(now) - kstDayStart(since)) / DAY) + 1;
}
/** The wallet against the executor's first balance record (deposits and withdrawals left out): balance / initial. */
export function multOf(a) {
  if (!a || a.state !== "ok" || a.balance == null || !(Number(a.initial) > 0)) return null;
  return Number(a.balance) / Number(a.initial);
}

/** The bot an executor's card follows (the summary's ``follows_ko``, else the paper bot every executor follows); ""
 *  before the first summary (never an old bot's name before the answer says so). */
export function botOfExec(d, x) {
  if (!d || !x) return "";
  return x.follows_ko || paperBotKo(d.trend_bot || null, d.paper ? d.paper.name_ko : null);
}
/** The mix bot's LED from its /api/v4/livebots/mix entry: {id: run | stale | halt | bad | none | wait, ko, why}. */
export function mixLed(b, failed = false, o = {}) {
  if (!b || !b.status) return failed ? {id: "bad", ko: "불러오지 못함", why: `${o.ko || "믹스 봇"} 기록을 불러오지 못했어요`} : {id: "wait", ko: "불러오는 중", why: null};
  const s = b.status, unit = s.unit || b.unit || o.unit || "paperbot-mixchop";
  if (s.state === "off") return {id: "none", ko: "꺼짐", why: `아직 켠 적 없어요 (기록 파일 없음) · 켜기: sudo systemctl start ${unit}`};
  if (s.state === "error") return {id: "bad", ko: "못 읽음", why: s.reason_ko || s.ko || "상태 파일을 읽지 못했어요"};
  if (s.state === "stopped") return {id: "stale", ko: "기록 멈춤", why: `35분 넘게 새 기록이 없어요 · 서버에서 systemctl status ${unit}`};
  const hs = ((b.halts || {}).items || []).filter((x) => x.sure);
  if (hs.length) return {id: "halt", ko: "새 진입 멈춤", why: hs.map((x) => x.ko).join(" · ")};
  return {id: "run", ko: "돌아가는 중", why: null};
}
/** The mix bot's last closed trades as a ring of n cells (oldest first, clockwise from the top), each {v: true (won) /
 *  false (lost) / null (P&L unknown or no trade yet), a0, a1}; wins, losses, have. */
export function tradeRing(recent, n = 20, gap = 3.2) {
  const xs = (recent || []).slice(-n);
  const step = 360 / n;
  const segs = Array.from({length: n}, (_, i) => ({v: i < xs.length ? (xs[i].win == null ? null : !!xs[i].win) : null, a0: i * step + gap / 2, a1: (i + 1) * step - gap / 2}));
  return {n, segs, have: xs.length, wins: xs.filter((x) => x.win === true).length, losses: xs.filter((x) => x.win === false).length};
}
/** May the mix bot enter now, in a word: "멈춤" / "진입 금지 시간 · 주말" / "보유 중" / "가능" / "몰라요". */
export function mixGate(b) {
  if (!b || !b.status || b.status.state === "off" || b.status.state === "error") return "—";
  if (b.status.state === "stopped") return "— (기록 멈춤)";
  if (((b.halts || {}).items || []).some((x) => x.sure)) return "멈춤";
  const bl = b.blocks || {};
  if (bl.state !== "ok") return "몰라요";
  if (bl.now && bl.now.blocked) return `진입 금지 시간${bl.now.kind ? ` · ${{weekend: "주말", usopen: "나스닥 개장", macro: "경제 발표"}[bl.now.kind] || ""}` : ""}`;
  if (b.position && b.position.state === "ok") return "보유 중 (한 번에 1개)";
  if (b.position && b.position.state !== "ok") return "몰라요";
  return b.status.state === "running" ? "가능 · 30분봉 신호를 기다려요" : "—";
}

/**
 * The light as a ring: n segments (the light's squares, oldest first = at the top, clockwise), each {v: true (won) /
 * false (lost) / null (no trade yet), a0, a1}; wins, have (closed trades in the window), need (wins the threshold asks
 * for: ceil(min_win x n), the executor's rule) and their angles on the outer track (winA, needA). n 0 = the light is off.
 */
export function ringModel(l, gap = 3.2) {
  const cells = lightCells(l);
  const n = cells.length;
  const min = l && l.min_win != null ? Number(l.min_win) : null;
  if (!n) return {n: 0, segs: [], wins: 0, have: 0, need: null, winA: 0, needA: null, min};
  const step = 360 / n;
  const segs = cells.map((v, i) => ({v, a0: i * step + gap / 2, a1: (i + 1) * step - gap / 2}));
  const wins = cells.filter((v) => v === true).length, have = cells.filter((v) => v != null).length;
  const need = l.need_wins != null ? Number(l.need_wins) : min != null ? Math.ceil(min * n - 1e-9) : null;
  return {n, segs, wins, have, need, min, winA: (wins / n) * 360, needA: need != null ? (Math.min(need, n) / n) * 360 : null};
}

/**
 * A value's angle on the gauge's step scale: the sorted anchor values `xs` (stop, entry, next lock steps) equally spaced
 * from -span to +span degrees, a value in between placed linearly between its two anchors; past the first / last anchor
 * it goes on at the next segment's rate up to `over` degrees further, then stops (the needle never leaves the dial).
 */
export function stepAngle(v, xs, span = 68, over = 20) {
  if (v == null || !Number.isFinite(Number(v)) || !xs || !xs.length) return null;
  const x = Number(v);
  if (xs.length === 1) return x > xs[0] ? over : x < xs[0] ? -over : 0;
  const k = xs.length - 1, seg = (2 * span) / k, at = (i) => -span + seg * i;
  if (x <= xs[0]) { const w = xs[1] - xs[0]; return Math.max(-span - over, at(0) - (w > 0 ? ((xs[0] - x) / w) * seg : 0)); }
  if (x >= xs[k]) { const w = xs[k] - xs[k - 1]; return Math.min(span + over, at(k) + (w > 0 ? ((x - xs[k]) / w) * seg : 0)); }
  for (let i = 0; i < k; i++) {
    if (x <= xs[i + 1]) { const w = xs[i + 1] - xs[i]; return at(i) + (w > 0 ? ((x - xs[i]) / w) * seg : 0); }
  }
  return at(k);
}

/**
 * The gauge of an open position. kind "paper": net ROE (the ladder's own number, paperbot/ladder.py: fees, slippage and
 * funding taken out) at the live mark, else the paper's own last mark; "live": the executor's ROE at the mark (before the
 * exit fee). Anchors, low to high: the stop (손절, or 잠금선 once locked), the entry, the next lock step (its trigger
 * 'at' and the lock it sets) and the one after it (afterNext: the server's next_lock.then, so the two-part ladder's
 * 11 % -> 15 % -> 20 % is drawn as the bot locks). Zones between anchors: loss (stop .. entry),
 * safe (entry .. a lock stop: profit already locked), run (toward the next step), lock (between the next two steps).
 * -> {kind, roe, anchors: [{k, v, price, lock?, angle}], zones: [{tone, a0, a1}], needle, entryA, xs} or null.
 */
export function gaugeModel(p, o = {}) {
  if (!p || !(Number(p.entry) > 0)) return null;
  const paper = o.kind !== "live";
  const at = (price) => (paper ? netRoe(p, price) : roeAt(p, price));
  let roe = Number(o.mark) > 0 ? at(o.mark) : null;
  if (roe == null && paper && p.last_mark_roe_net != null) roe = Number(p.last_mark_roe_net);
  const entry = paper ? at(p.entry) : 0;
  const stop = Number(p.stop) > 0 ? at(p.stop) : null;
  const nx = p.next_lock && p.next_lock.at != null ? p.next_lock : null;
  const rt = paper ? Number(p.round_trip || 0) : 0, ff = paper ? Number(p.funding_frac || 0) : 0;
  const priceAt = (r) => roePrice(Number(p.side), Number(p.entry), Number(p.leverage), r, rt, ff);
  const anchors = [];
  if (stop != null) anchors.push({k: "stop", v: stop, price: Number(p.stop), locked: !!p.locked});
  if (entry != null) anchors.push({k: "entry", v: entry, price: Number(p.entry)});
  if (nx) {
    anchors.push({k: "next", v: Number(nx.at), lock: nx.lock != null ? Number(nx.lock) : null, price: nx.price != null ? Number(nx.price) : priceAt(Number(nx.at))});
    const th = afterNext(nx, o.ladder);
    if (th) anchors.push({k: "next2", v: th.at, lock: th.lock, price: priceAt(th.at)});
  }
  anchors.sort((a, b) => a.v - b.v || (a.k === "entry" ? -1 : 1));
  const xs = anchors.map((a) => a.v);
  for (const a of anchors) a.angle = stepAngle(a.v, xs);
  const zones = [];
  const first = anchors.length ? anchors[0].angle : -68, last = anchors.length ? anchors[anchors.length - 1].angle : 68;
  zones.push({tone: "out", a0: -88, a1: first});
  for (let i = 0; i + 1 < anchors.length; i++) {
    const a = anchors[i], b = anchors[i + 1];
    const tone = a.k === "stop" && b.k === "entry" ? "loss" : a.k === "entry" && b.k === "stop" ? "safe" : a.k === "next" ? "lock" : "run";
    zones.push({tone, a0: a.angle, a1: b.angle});
  }
  zones.push({tone: "out", a0: last, a1: 88});
  const e = anchors.find((a) => a.k === "entry");
  return {kind: paper ? "paper" : "live", roe, anchors, zones, xs, needle: stepAngle(roe, xs), entryA: e ? e.angle : null};
}

/**
 * The ladder step after the next one {at, lock}: the server's own (next_lock.then: paperbot/ladder2.py, both forms, e.g.
 * the two-part ladder's 15 % -> 12 % after 11 % -> 10 %), else (an answer without it) one ladder step more. null without.
 */
export function afterNext(nx, ladder) {
  if (!nx || nx.at == null) return null;
  if (nx.then && nx.then.at != null) return {at: Number(nx.then.at), lock: nx.then.lock != null ? Number(nx.then.lock) : null};
  const step = ladder && ladder.step != null ? Number(ladder.step) : null;
  return step != null && step > 0 ? {at: Number(nx.at) + step, lock: nx.lock != null ? Number(nx.lock) + step : null} : null;
}

/**
 * The first ladder lock of a paper position and the reward against its risk (손익비, 첫 잠금 기준): the lock the first step
 * sets (first_lock, e.g. +10 % net ROE) against the loss at the first stop (the initial stop's net ROE). Also the
 * trigger (first_lock + trigger_gap, e.g. 11 %) and their prices. null without a position, the ladder or the stop.
 */
export function firstLock(p, ladder) {
  if (!p || !ladder || ladder.first_lock == null || ladder.trigger_gap == null || !(Number(p.entry) > 0)) return null;
  const lock = Number(ladder.first_lock), at = lock + Number(ladder.trigger_gap);
  const rt = Number(p.round_trip || 0), ff = Number(p.funding_frac || 0);
  const price = (r) => roePrice(Number(p.side), Number(p.entry), Number(p.leverage), r, rt, ff);
  const stop0 = Number(p.stop_initial) > 0 ? Number(p.stop_initial) : !p.locked && Number(p.stop) > 0 ? Number(p.stop) : null;
  const risk = stop0 != null ? netRoe(p, stop0) : null;
  return {lock, at, lockPrice: price(lock), atPrice: price(at), risk, rr: risk != null && risk < 0 ? lock / -risk : null};
}

/** The frame's side label: '추세판단 봇 · COMBO@MIX · 보기만 · 주문 없음' (tb: the summary's trend_bot; null: another bot, its
 *  config name (name: the summary's paper.name_ko) or the old 'A+C 합본'; undefined: no summary yet, no name). */
export function sideBotKo(tb, name) {
  return `${tb === undefined ? "" : `${paperBotKo(tb, name)} · `}COMBO@MIX · 보기만 · 주문 없음`;
}

/** A time's angle on the day's dial (0 = 00:00 KST at the top, clockwise, 360 = 24:00). */
export const dayAngle = (ms, d0) => ((Number(ms) - Number(d0)) / DAY) * 360;
/**
 * The pause windows that touch the day starting at d0, clipped to it: [{why, ko, kind, from, to, a0, a1}]. spans: the
 * calendar's spans (from now on) plus its items' own pause windows (the day's releases already past): the same window
 * twice counts once.
 */
export function dayArcs(spans, items, d0) {
  const d1 = Number(d0) + DAY, seen = new Set(), out = [];
  const all = [...(spans || []), ...(items || []).filter((x) => x && x.pause_from != null && x.pause_to != null)
    .map((x) => ({from: x.pause_from, to: x.pause_to, why: "macro", ko: `${x.kind_ko} 앞뒤`, kind: x.kind}))];
  for (const sp of all) {
    if (!sp || sp.from == null || sp.to == null) continue;
    const key = `${sp.why}|${sp.from}|${sp.to}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const a = Math.max(Number(sp.from), Number(d0)), b = Math.min(Number(sp.to), d1);
    if (b > a) out.push({why: sp.why, ko: sp.ko, kind: sp.kind || null, from: Number(sp.from), to: Number(sp.to), a0: dayAngle(a, d0), a1: dayAngle(b, d0)});
  }
  return out.sort((x, y) => x.a0 - y.a0);
}
/** Today's entries (the summary's fills of kind entry within the day) as dots: [{acct, sym, side, t, a, open}]; with
 *  ``since`` (the 추세판단 봇's start: the summary's trend_bot.since) only those from it on (before it: the bot before it's). */
export function dayDots(fills, d0, since = null) {
  const d1 = Number(d0) + DAY, from = Math.max(Number(d0), since == null ? -Infinity : Number(since));
  return (fills || []).filter((f) => f && f.kind === "entry" && f.t != null && f.t >= from && f.t < d1)
    .map((f) => ({acct: f.acct, sym: f.symbol, side: f.side, t: f.t, a: dayAngle(f.t, d0), open: !!f.open}))
    .sort((x, y) => x.t - y.t);
}
/** The dial's '오늘 진입' line: '2번 (페이퍼(연습) · 바이비트)', '아직 없음'; the 추세판단 봇 started today (``since`` within the
 *  day: the window was cut) says so: '새 봇 시작 23:28 뒤 아직 없음'. names: the accounts' names of the dots. */
export function dayEntriesKo(dots, d0, since, names) {
  const n = (dots || []).length;
  const said = n ? `${fmt.int(n)}번 (${[...new Set(names || [])].join(" · ")})` : "아직 없음";
  const cut = since != null && Number(since) > Number(d0) && Number(since) < Number(d0) + DAY;
  return cut ? `새 봇 시작 ${fmt.hm(Number(since))} 뒤 ${said}` : said;
}

/** A tile's brightness 0-4 from this week's signals n against the busiest strategy's max (null: the count is unknown). */
export function tileLevel(n, max) {
  if (n == null || !Number.isFinite(Number(n))) return null;
  if (!(Number(n) > 0)) return 0;
  if (!(Number(max) > 0)) return 1;
  return Math.max(1, Math.min(4, Math.ceil((Number(n) / Number(max)) * 4)));
}
/**
 * The strategies of the config the bot runs (rank rows in_config, in the config's order) as tiles: {code, n (this
 * week's signals, null when the signal records could not be read), today, entered, lvl, hold, type, paper, last_ms,
 * last_ko, tfs, settings}. Strategies traded only under an earlier config are left out (the page says how many).
 */
export function tilesOf(rank) {
  const known = !!(rank && rank.signals && rank.signals.state === "ok");
  const rows = ((rank && rank.rows) || []).filter((r) => r && r.in_config !== false);
  const cnt = (r, span, k) => (r.sig && r.sig[span] && r.sig[span][k] != null ? Number(r.sig[span][k]) : 0);
  const max = known ? Math.max(0, ...rows.map((r) => cnt(r, "week", "signals"))) : 0;
  return rows.map((r) => {
    const n = known ? cnt(r, "week", "signals") : null;
    return {code: r.strategy, n, today: known ? cnt(r, "today", "signals") : null, entered: known ? cnt(r, "week", "entered") : null,
      lvl: tileLevel(n, max), hold: !!r.open, type: (r.bt && r.bt.type_ko) || null, paper: r.paper || null,
      last_ms: r.sig ? r.sig.last_ms : null, last_ko: r.sig ? r.sig.last_ko : null, tfs: r.tfs || [], settings: r.n_settings || 0};
  });
}

/** No executor of the summary follows the main paper bot (the 추세판단 봇) any more (owners 10-29: switched off). */
export const mainOff = (d) => !!d && Array.isArray(d.execs) && d.execs.length > 0 && d.execs.every((x) => x && "bot" in x)
  && !d.execs.some((x) => x.bot === "paper");
const MAIN_OFF_KO = "10/29부터 따라가는 실거래가 없어요 · 가운데 그림은 그 봇의 매매법이에요 · 지금 거래는 아래 계좌 카드의 봇들이 해요";
/**
 * What the centre says while no position is open: {tone: ok | warn | bad | wait, head, sub, until, on (the ring turns)}. The
 * ring turns only while the paper bot's record is fresh (it is really looking at every bar); a pause (weekend, a US
 * release) says why and until when; both executors halted says that no real money follows.
 */
export function idleWords(d, cal) {
  if (!d) return {tone: "wait", head: "불러오는 중", sub: null, until: null, on: false};
  const p = d.paper || {};
  // owners 10-29: the 추세판단 봇 switched off (no executor follows it): its stopped record is no alarm
  if (mainOff(d) && (p.state !== "ok" || p.stale)) return {tone: "wait", head: "추세판단 봇 꺼 둠", sub: MAIN_OFF_KO, until: null, on: false};
  if (p.state !== "ok") {
    return {tone: "bad", head: p.state === "error" ? "페이퍼 봇 기록을 못 읽음" : "페이퍼 봇 기록 수집 전", sub: p.reason_ko || null, until: null, on: false};
  }
  if (p.stale) return {tone: "bad", head: "페이퍼 봇 기록 멈춤", sub: "5분 넘게 새 기록이 없어 신호를 볼 수 없어요", until: null, on: false};
  const c = cal && cal.now;
  if (c && c.paused) return {tone: "warn", head: `쉬는 중 · ${c.pause_ko || "진입 쉬는 시간"}`, sub: "신호는 계속 보지만 새 진입은 하지 않아요", until: c.pause_until || null, on: true};
  const ex = d.execs || [];
  const halted = ex.filter((x) => x.record && x.record.state === "ok" && x.record.halted);
  if (ex.length && halted.length === ex.length) {
    return {tone: "bad", head: "대기 중 · 실행기 둘 다 멈춤", sub: "페이퍼는 계속 신호를 보지만 사람이 풀 때까지 진짜 돈은 따라가지 않아요", until: null, on: true};
  }
  return {tone: "ok", head: "대기 중 · 신호를 기다리는 중", sub: null, until: null, on: true};
}

// ---------------------------------------------------------------- the ring of strategies (the centre's particle torus)
// The torus IS the bot: one arc of points per strategy of the config it runs, its length by that strategy's settings
// (27 strategies, 95 settings), brightness by this week's signals (tileLevel), the one holding the position in the
// position colour. Model space: the ring in the x-z plane (major radius 1, tube radius TUBE), y up.
export const TUBE = 0.34;
export const TILT = 0.47;                            // the view from about 27° above the ring's plane
export const CAM = 3.4;                              // camera distance (perspective)
/** A small seeded random (xorshift): the same points every time for the same seed. */
export function prng(seed = 7) {
  let x = (Number(seed) >>> 0) || 1;
  return () => { x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0; return x / 4294967296; };
}
/** The strategies' arcs around the ring (degrees), each as long as its share of the settings, `gap` degrees apart:
 *  [{code, a0, a1}]. groups: [{code, settings}]; a group without settings counts as one. */
export function arcsOf(groups, gap = 2) {
  const gs = groups || [];
  if (!gs.length) return [];
  const w = gs.map((g) => Math.max(1, Number(g.settings) || 1)), total = w.reduce((a, b) => a + b, 0);
  const g0 = gs.length > 1 ? gap : 0, free = 360 - g0 * gs.length;
  let a = 0;
  return gs.map((g, i) => { const len = (free * w[i]) / total, out = {code: g.code, a0: a + g0 / 2, a1: a + g0 / 2 + len}; a += len + g0; return out; });
}
/** A point of the torus in model space: u the angle around the ring (degrees), v around the tube (radians). */
export function torusXYZ(uDeg, v, R = 1, r = TUBE) {
  const u = (Number(uDeg) * Math.PI) / 180, c = R + r * Math.cos(v);
  return [c * Math.cos(u), r * Math.sin(v), c * Math.sin(u)];
}
/** About n points over the arcs (each arc's share by its length, at least 4), seeded: [{g (arc index), x, y, z}]. */
export function torusPoints(arcs, n, seed = 7) {
  const rnd = prng(seed), out = [];
  const total = (arcs || []).reduce((s, a) => s + (a.a1 - a.a0), 0);
  (arcs || []).forEach((a, g) => {
    const k = Math.max(4, Math.round((n * (a.a1 - a.a0)) / (total || 1)));
    for (let i = 0; i < k; i++) {
      const [x, y, z] = torusXYZ(a.a0 + rnd() * (a.a1 - a.a0), rnd() * Math.PI * 2);
      out.push({g, x, y, z});
    }
  });
  return out;
}
/** Rotate a model point by `rot` around the vertical axis, tilt the view by `tilt`, project with the camera at `cam`:
 *  [x, y (screen up), depth (positive = farther), k (the perspective scale: above 1 = nearer)]. */
export function project(x, y, z, rot, tilt = TILT, cam = CAM) {
  const cr = Math.cos(rot), sr = Math.sin(rot), ct = Math.cos(tilt), st = Math.sin(tilt);
  const x1 = x * cr - z * sr, z1 = x * sr + z * cr;
  const y2 = y * ct + z1 * st, z2 = -y * st + z1 * ct;
  const k = cam / (cam + z2);
  return [x1 * k, y2 * k, z2, k];
}
/** The ring's projected box in model units (any turn gives the same box: the torus is round): {x0, x1, y0, y1}. */
export function ringBox(tilt = TILT, cam = CAM) {
  let x0 = 0, x1 = 0, y0 = 0, y1 = 0;
  for (let u = 0; u < 360; u += 6) {
    for (let j = 0; j < 12; j++) {
      const [x, y, z] = torusXYZ(u, (j / 12) * Math.PI * 2);
      const [px, py] = project(x, y, z, 0, tilt, cam);
      x0 = Math.min(x0, px); x1 = Math.max(x1, px); y0 = Math.min(y0, py); y1 = Math.max(y1, py);
    }
  }
  return {x0, x1, y0, y1};
}
const BOX = ringBox();
/** Fit the ring into a w x h box (px): its width at most fx of w, its height at most fy of h, centred on its real
 *  (perspective-shifted) middle: {sc (px per model unit), cx, cy (the model origin on the screen)}. */
export function fitRing(w, h, fx = 0.66, fy = 0.86) {
  const bw = BOX.x1 - BOX.x0, bh = BOX.y1 - BOX.y0;
  const sc = Math.max(1, Math.min((w * fx) / bw, (h * fy) / bh));
  return {sc, cx: w / 2 - ((BOX.x0 + BOX.x1) / 2) * sc, cy: h / 2 + ((BOX.y0 + BOX.y1) / 2) * sc};
}
/** A point on the quadratic curve from s through the pull of c to e at t (0..1): [x, y]. */
export function bezier(s, c, e, t) {
  const u = 1 - t;
  return [u * u * s[0] + 2 * u * t * c[0] + t * t * e[0], u * u * s[1] + 2 * u * t * c[1] + t * t * e[1]];
}
/** A strategy arc's brightness from its tile level (null = the signal count is unknown). */
export const glowOf = (lvl) => (lvl == null ? 0.6 : [0.55, 0.72, 0.84, 0.94, 1][Math.max(0, Math.min(4, lvl))]);

/** The pause now, from /now or the calendar: {ko, until} or null. */
export function pauseOf(now, cal) {
  const c = cal && cal.now;
  if (c && c.paused) return {ko: c.pause_ko || "진입 쉬는 시간", until: c.pause_until || null};
  const it = ((now && now.items) || []).find((i) => (i.id === "weekend" || i.id === "macro" || i.id === "usopen") && i.ok === false);
  return it ? {ko: it.ko, until: (now && now.pause_until) || (it.detail && it.detail.until) || null} : null;
}

/**
 * The real milestones an executor has reached (keys, never guessed): "win1" its first closed trade with a profit, "x1.5"
 * and "x2" its wallet at 1.5 / 2 times its first balance record (deposits left out).
 */
export function milestonesOf(a) {
  if (!a || a.state !== "ok") return [];
  const out = [];
  if (a.stats && Number(a.stats.wins) > 0) out.push("win1");
  const m = multOf(a);
  if (m != null && m >= 1.5) out.push("x1.5");
  if (m != null && m >= 2) out.push("x2");
  return out;
}
/**
 * The milestones to celebrate now: reached ones that were not reached at the page's previous answer (`before`; null =
 * this is the first look: nothing is new then, except a first win whose exit is at most `recentMs` old) and that this
 * browser has never celebrated (`seen`, from localStorage).
 */
export function freshMilestones(before, reached, seen, firstWinAt = null, now = 0, recentMs = RECENT_MS) {
  const done = new Set(seen || []);
  return (reached || []).filter((k) => !done.has(k) && (before ? !before.includes(k)
    : k === "win1" && firstWinAt != null && now - firstWinAt <= recentMs && firstWinAt <= now + 60000));
}

/** The last closed trade for the result card: the newest live exit (바이비트 / MEXC / 딥코인), else the paper's (labelled), with its
 *  entry (the same trade's entry fill): {exit, entry, paper} or null. */
export function lastClosed(fills) {
  const xs = (fills || []).filter((f) => f && f.kind === "exit" && f.t != null).sort((a, b) => b.t - a.t);
  const paperish = (f) => isPaperId(f.acct);                                        // the other paper bots' fills are paper too
  const pick = xs.find((f) => !paperish(f)) || xs.find((f) => f.acct === "paper") || xs.find(paperish) || null;
  if (!pick) return null;
  const ek = String(pick.key || "").replace(/:x:/, ":e:");
  const entry = (fills || []).find((f) => f && f.kind === "entry" && f.key === ek) || null;
  return {exit: pick, entry, paper: paperish(pick)};
}

/** The 실시간 feed: the newest fills, WARN / CRITICAL events and the last signal, newest first: [{key, t, kind, ...}]. */
export function feedRows(d, nowAns, max = 8) {
  const out = [];
  for (const f of (d && d.fills) || []) {
    const kind = f.kind === "entry" ? "entry" : f.reason === "LOCK" || f.reason === "TP" ? "lock" : f.reason === "SL" || f.reason === "LIQ" ? "stop" : "exit";
    out.push({key: "f:" + f.key, t: f.t, kind, acct: f.acct, f});
  }
  for (const e of (d && d.events) || []) out.push({key: `e:${e.ex}:${e.id}`, t: e.ts, kind: e.level === "CRITICAL" ? "crit" : "warn", acct: e.ex, e});
  const ls = nowAns && nowAns.last_signal;
  if (ls && ls.t != null) out.push({key: `s:${ls.t}:${ls.symbol}:${ls.strategy}`, t: ls.t, kind: "sig", sig: ls});
  return out.filter((r) => r.t != null).sort((a, b) => b.t - a.t).slice(0, max);
}

// ================================================================ words
const usdS = (v) => (v == null || !Number.isFinite(Number(v)) ? "—" : `${Number(v) > 0 ? "+" : Number(v) < 0 ? fmt.MINUS : ""}$${fmt.money(Math.abs(Number(v)))}`);
const usd0 = (v) => (v == null || !Number.isFinite(Number(v)) ? "—" : `$${fmt.money(v)}`);
const stratName = (code) => (code ? fmt.stratKo(code) : "매매법 모름");
const ageKo = (ms) => (ms ? fmt.ago(ms, serverNow()) : "—");
const by = (xs, id) => (xs || []).find((x) => x && x.id === id) || null;
const acctName = (id) => (ACCT[id] ? ACCT[id].ko : String(id || "—"));
/** money of an account in its own unit: real dollars for the executors, 모의 numbers for the paper */
const moneyOf = (id, v, sign = true) => (id === "paper" ? `${fmt.money(v, sign)} (모의)` : sign ? usdS(v) : usd0(v));

/** A /now item's detail in words: {text, until} (until: a countdown's end, ms). */
export function whyDetail(it) {
  const d = (it && it.detail) || null;
  if (!d) return null;
  switch (it.id) {
    case "weekend": return d.until ? {text: `${fmt.kst(d.until)}까지 쉼`, until: d.until} : null;
    case "macro": return d.until ? {text: `발표 ${fmt.hm(d.ts)} · ${fmt.hm(d.until)}까지 쉼`, until: d.until} : null;
    case "paper": case "exec":
      if (d.reason_ko) return {text: d.reason_ko};
      return d.as_of ? {text: `마지막 기록 ${ageKo(d.as_of)}`} : null;
    case "position": {
      const bits = [d.symbol ? `${fmt.coin(d.symbol)} ${fmt.sideKo(d.side)}` : null, d.strategy_id ? `${stratName(d.strategy_id)}${d.timeframe ? " " + fmt.tfKo(d.timeframe) : ""}` : null,
        d.entry_time ? `${fmt.hm(d.entry_time)} 진입` : null, d.last_mark_roe_net != null ? `순ROE ${fmt.pct(d.last_mark_roe_net, 1)}` : null];
      return {text: bits.filter(Boolean).join(" · ")};
    }
    case "paper_halt": case "halt": return d.reason ? {text: `이유: ${d.reason}`} : null;
    case "light": {
      if (!d.n) return null;
      const rule = d.min_win != null ? `기준 ${fmt.pct(d.min_win, 0, false)}` : "";
      if (d.have != null && d.have < d.n) return {text: `페이퍼 거래 ${fmt.int(d.have)}/${fmt.int(d.n)}번 쌓임 · ${rule}`};
      return {text: `최근 ${fmt.int(d.n)}번 중 ${fmt.int(d.wins)}번 이김 · ${rule} (${fmt.int(d.need_wins)}번)`};
    }
    default: return null;
  }
}

/** The ticker's items, only numbers the server sent: [{k, text, tone}] (k: a stable key, so a new number changes the text in
 *  place and the scroll goes on). */
export function tickerItems(d, nowAns, cal) {
  const out = [];
  if (!d) return out;
  const accts = d.accts || [];
  const ids = execIds(d);
  for (const id of ids) {
    const a = by(accts, id);
    const m = multOf(a);
    out.push({k: id, text: !a ? `${acctName(id)} —` : a.state !== "ok" ? `${acctName(id)} ${a.state === "error" ? "못 읽음" : "수집 전"}`
      : `${acctName(id)} ${a.balance == null ? "잔고 기록 전" : usd0(a.balance)}${m != null ? ` ×${fmt.num(m, 2)}` : ""}${a.halted ? " · 멈춤" : ""}`,
    tone: a && a.state === "ok" && a.halted ? "down" : null});
  }
  const both = ids.map((id) => by(accts, id));
  if (both.every((a) => a && a.state === "ok" && a.balance != null)) out.push({k: "sum", text: `실거래 합계 ${usd0(both.reduce((x, a) => x + Number(a.balance), 0))}`});
  const t = liveToday(accts);
  if (t) out.push({k: "today", text: t.trades ? `오늘 실거래 ${fmt.int(t.trades)}번 ${usdS(t.pnl)}` : "오늘 실거래 닫힌 거래 없음", tone: t.trades ? fmt.tone(t.pnl, fmt.money(t.pnl)) : null});
  for (const x of d.execs || []) out.push({k: "light:" + x.id, text: `신호등 ${acctName(x.id)} ${lightWords(x.light).short}`, tone: {good: "up", bad: "down", wait: "warn"}[lightWords(x.light).tone] || null});
  const pa = by(accts, "paper");
  const p = pa && pa.state === "ok" ? pa.position : null;
  if (p) out.push({k: "pos", text: `포지션 ${fmt.coin(p.symbol)} ${fmt.sideKo(p.side)} ${fmt.lev(p.leverage)}${p.last_mark_roe_net != null ? ` 순ROE ${fmt.pct(p.last_mark_roe_net, 1)}` : ""}${p.locked ? " 잠금" : ""}`});
  else if (pa && pa.state === "ok") out.push({k: "pos", text: "포지션 없음 · 신호 기다리는 중"});
  const cp = d.checkpoint;
  if (cp) out.push({k: "cp", text: cp.ready ? `${fmt.int(cp.trades)}번 판단 도착` : `${fmt.int(cp.trades)}번 판단까지 ${fmt.int(cp.left)}번 (페이퍼 ${fmt.int(cp.n)}/${fmt.int(cp.trades)})`});
  const ws = (nowAns && nowAns.pending && nowAns.pending.state === "ok" && nowAns.pending.waits) || [];
  if (ws.length) {
    const w = ws[0], ww = waitWords(w);
    out.push({k: "wait", text: `⏳ 진입 대기 ${fmt.coin(w.symbol)} ${fmt.sideKo(w.side)} · ${ww.move || "기준가 못 읽음"}${ww.left ? ` · ${ww.left}` : ""}${ws.length > 1 ? ` 외 ${fmt.int(ws.length - 1)}개` : ""}`, tone: "warn"});
  }
  const ls = nowAns && nowAns.last_signal;
  if (ls) out.push({k: "sig", text: `마지막 신호 ${fmt.coin(ls.symbol)} ${fmt.sideKo(ls.side)} · ${ls.ko || ls.stage || ""}`});
  const nx = cal && cal.now && cal.now.next;
  if (nx) out.push({k: "pause", text: `다음 쉬는 시간 ${nx.ko || "쉼"} ${fmt.kst(nx.from)}`});
  return out;
}

// ================================================================ ⏳ 진입 대기 (the /now answer's `pending`, owners 10/19)
/** How close a waiting break is to its level, for the small bar: 1 at (or past) the level, 0 at `scale` (2 %) away or
 *  farther; null without a level (never a guessed distance). */
export function closeness(w, scale = 0.02) {
  if (!w) return null;
  if (w.touched === true) return 1;
  if (w.to_go == null || !Number.isFinite(Number(w.to_go))) return null;
  return Math.max(0, Math.min(1, 1 - Number(w.to_go) / scale));
}
/** A wait's deadline by this page's clock: the time of the answer + the server's own left_ms (else its until). */
export const waitEnd = (w, fetchedAt) => (!w ? null : w.left_ms != null && fetchedAt ? Number(fetchedAt) + Number(w.left_ms) : w.until != null ? Number(w.until) : null);
/** A wait in words: {move: "101.00 위로 올라가면 진입" (a break) | "99.00까지 내려오면 진입 (되돌림)" (the 추세판단 봇's
 *  pullback) | null (no level), last, left: "1.00% 남음" | null, touch: the pill once touched}. */
export function waitWords(w) {
  const long = Number(w && w.side) > 0, pull = !!w && w.kind === "pullback";
  return {touch: pull ? "되돌림 닿음 · 진입 확인 중" : "돌파함 · 진입 확인 중",
    move: !w || w.level == null ? null : pull ? `${fmt.price(w.level)}까지 ${long ? "내려오면" : "올라오면"} 진입 (되돌림)`
      : `${fmt.price(w.level)} ${long ? "위로 올라가면" : "아래로 내려가면"} 진입`,
    last: !w || w.last == null ? null : fmt.price(w.last),
    left: !w || w.touched === true || w.to_go == null ? null : `${fmt.pct(Math.max(0, Number(w.to_go)), 2, false)} 남음`};
}
/** The next bar closes in words: "15분봉 마감 19:15 KST · 바로 진입 0개 · 돌파 대기 1개". */
export const closeWords = (c) => (c.pull ? `${fmt.tfKo(c.tf)}봉 마감 ${fmt.hm(c.next_ms)} KST · 되돌림 진입 ${fmt.int(c.pull)}개`
  : `${fmt.tfKo(c.tf)}봉 마감 ${fmt.hm(c.next_ms)} KST · 바로 진입 ${fmt.int(c.now)}개 · 돌파 대기 ${fmt.int(c["break"])}개`);
export const WAIT_NOTE_KO = "진입 대기 = 신호는 나왔고 정한 가격(되돌림 또는 돌파)을 기다리는 중. 진입 확정이 아니에요. 시간 안에 안 닿으면 진입 없음.";
export const WAIT_TG_KO = "텔레그램에도 ⏳ 진입 대기 알림이 한 번 가요 (끄기: PAPERBOT_LIVE_WAIT_MSGS=0)";

/**
 * The ⏳ 진입 대기 card's body from the /now answer (n) fetched at `fetchedAt` (serverNow ms): each waiting break (coin, side,
 * strategy · timeframe, the level to cross, the last price, how far to go with a small bar, the deadline counting down
 * in [data-wuntil], 돌파함 · 진입 확인 중 once touched; 기준가 못 읽음 + the rule bot's file when there is no level), else
 * '지금 기다리는 진입 없음' and the next bar closes; the reason a wait cannot become an entry now (pending_blocked_ko); the
 * honest lines. -> {el, rows: Map(key -> row element)}.
 */
export function waitCard(n, fetchedAt) {
  const rows = new Map();
  if (!n) return {el: h("div", {class: "lbh-wcard"}, motion.shimmer(3)), rows};
  const pd = n.pending;
  const kids = [];
  if (n.pending_blocked_ko) kids.push(h("p", {class: "lbh-wblock"}, h("b", null, "지금은 진입으로 이어지지 않아요"), ` · ${n.pending_blocked_ko}`));
  if (!pd) kids.push(h("p", {class: "lbh-wnone"}, ui.notYet("수집 전"), " 진입 대기 정보가 아직 서버에 없어요"));
  else if (pd.state !== "ok") {
    kids.push(h("p", {class: "lbh-wnone"}, ui.pill(pd.state === "error" ? "못 읽음" : "수집 전", pd.state === "error" ? "bad" : ""),
      ` 진입 대기 기록: ${pd.reason_ko || "읽지 못했어요"}`));
  } else if (!(pd.waits || []).length) {
    kids.push(h("p", {class: "lbh-wnone"}, "지금 기다리는 진입 없음"),
      (pd.closes || []).length ? h("ul", {class: "lbh-wcl"}, pd.closes.map((c) => h("li", null, h("i", {class: "lbh-wcli", "aria-hidden": "true"}), closeWords(c)))) : null);
  } else {
    for (const w of pd.waits) {
      const long = Number(w.side) > 0, ww = waitWords(w), cl = closeness(w), end = waitEnd(w, fetchedAt);
      const row = h("div", {class: ["lbh-pwrow", w.touched === true ? "touched" : ""], dataset: {key: w.key}},
        h("div", {class: "lbh-wth"}, h("b", {class: "lbh-wcoin"}, fmt.coin(w.symbol)), h("b", {class: ["lbh-wside", long ? "up" : "down"]}, fmt.sideKo(w.side)),
          h("span", {class: "lbh-wstrat"}, `${w.strategy ? fmt.stratKo(w.strategy) : "매매법 모름"} · ${fmt.tfKo(w.tf)}`),
          end != null ? h("span", {class: "lbh-wcd"}, h("b", {class: "num", dataset: {wuntil: end}}, clockOf((end - serverNow()) / 1000))) : null),
        ww.move ? h("p", {class: "lbh-wmove"}, ww.move)
          : h("p", {class: "lbh-wnolvl"}, `기준가 못 읽음 (규칙봇 1분봉 파일: ${pd.rule_path || "경로 모름"}${pd.rule_state && pd.rule_state !== "ok" ? `, ${pd.rule_state === "error" ? "못 읽음" : "없음"}` : ""})`),
        ww.move ? h("div", {class: "lbh-wnow"}, h("span", null, "지금 ", h("b", {class: "num"}, ww.last || "—")), ww.left ? h("span", {class: "num lbh-wleft"}, ww.left) : null) : null,
        cl != null ? h("div", {class: "lbh-wbar", role: "img", "aria-label": ww.left || ww.touch}, h("i", {style: {transform: `scaleX(${cl.toFixed(3)})`}})) : null,
        w.touched === true ? h("p", {class: "lbh-wtouch"}, ui.pill(ww.touch, "good")) : null);
      rows.set(w.key, row);
      kids.push(row);
    }
  }
  kids.push(h("p", {class: "lbh-wnote"}, WAIT_NOTE_KO), h("p", {class: "lbh-wnote"}, WAIT_TG_KO));
  return {el: h("div", {class: "lbh-wcard"}, kids), rows};
}

// ================================================================ 진입 가능성 TOP 5 (the /now answer's `likely`, owners 10/19)
/** A share already in percent (the likely file's numbers): "38%", under 10 one decimal "7.4%"; null -> "—". */
export const pctK = (x) => (x == null || !Number.isFinite(Number(x)) ? "—" : fmt.pctOf(Number(x), Number(x) < 10 ? 1 : 0));
export const LIKELY_FOOT_KO = "이길 확률이 아니라 신호가 나오는 빈도예요";
// the panel's title and subtitle: the 5-year table, or the 추세판단 봇's (no table for its rules: the directions, the replay)
export const LIKELY_HEAD = {table: ["진입 가능성 TOP 5", "4시간 안에 신호가 나온 빈도 · 5년 백테스트"],
  trend: ["진입 가능성", "지금 추세가 받는 방향 · 재현(가상)"]};
const LIKELY_TREND_FOOT_KO = "이길 확률이 아니라 진입이 얼마나 자주인지예요";
const GROUP_KO = {mt: "월~목", fri: "금요일", sat: "토요일", sun: "일요일"};
/**
 * The card: the whole bot's line ("4시간 안 진입 신호: 지금 같은 시간엔 38% (5년 42%) · 보통 4.5시간 뒤"), then the ranked rows
 * (rank, strategy, type, the recent 4-hour share big with a bar against the whole bot's, the 5-year share small, ⏳ when a
 * break waits), the honest note and a link to the 순위 tab. missing / error -> 수집 전 / 못 읽음 with the reason. href: the
 * 순위 tab's address.
 */
export function likelyCard(n, href) {
  if (!n) return h("div", {class: "lbh-lcard"}, motion.shimmer(4));
  const lk = n.likely;
  const foot = h("p", {class: "lbh-lfoot"}, `${LIKELY_FOOT_KO} · `, h("a", {href: href || "#/livebots/rank"}, "자세히: 순위 탭"));
  if (!lk) return h("div", {class: "lbh-lcard"}, h("p", {class: "lbh-wnone"}, ui.notYet("수집 전"), " 진입 가능성 정보가 아직 서버에 없어요"), foot);
  if (lk.state === "trend") {                            // the 추세판단 봇: no table for its rules (dash/more/livebots.py likely_trend)
    const take = takingKo(lk.taking), ex = expectLines(lk.expect);
    return h("div", {class: "lbh-lcard"},
      h("div", {class: "lbh-lbot"}, h("p", null, "지금 추세가 받는 방향 ", h("b", null, take.length ? `${take.length}곳` : "없음")),
        h("span", {class: "lbh-lcell"}, take.length ? take.join(" · ") : takingNoneKo(lk.hold_entry))),
      ex.length ? h("ul", {class: "lbh-ltrend"}, ex.map((x) => h("li", null, x))) : null,
      h("p", {class: "lbh-wnote"}, `가상(재현) 숫자 · ${lk.reason_ko || ""}`),
      lk.expect && lk.expect.note_ko ? h("p", {class: "lbh-wnote"}, lk.expect.note_ko) : null,
      h("p", {class: "lbh-lfoot"}, `${LIKELY_TREND_FOOT_KO} · `, h("a", {href: href || "#/livebots/rank"}, "자세히: 순위 탭")));
  }
  if (lk.state !== "ok") {
    return h("div", {class: "lbh-lcard"}, h("p", {class: "lbh-wnone"}, ui.pill(lk.state === "error" ? "못 읽음" : "수집 전", lk.state === "error" ? "bad" : ""),
      ` 진입 가능성 기준표: ${lk.reason_ko || "읽지 못했어요"}`), foot);
  }
  const b = lk.bot || {}, w4 = b.w4 || {}, nx = b.next_h_median || {}, cell = lk.cell || {};
  const scale = Number(w4.recent) > 0 ? Number(w4.recent) : Math.max(1, ...(lk.top || []).map((r) => Number(r.p && r.p.w4 && r.p.w4.recent) || 0));
  const head = h("div", {class: "lbh-lbot"},
    h("p", null, "4시간 안 진입 신호: 지금 같은 시간엔 ", h("b", {class: "num"}, pctK(w4.recent)), ` (5년 ${pctK(w4.all)})`,
      nx.recent != null ? ` · 보통 ${fmt.num(nx.recent, 1)}시간 뒤` : ""),
    h("span", {class: "lbh-lcell"}, `${GROUP_KO[cell.group] || "—"} ${cell.hour != null ? `${String(cell.hour).padStart(2, "0")}시` : ""} 기준 · 봇 전체 · 최근 2025~26년`));
  const rows = (lk.top || []).map((r) => {
    const v = r.p && r.p.w4 ? r.p.w4.recent : null, all = r.p && r.p.w4 ? r.p.w4.all : null, wt = (r.waits || []).length;
    return h("li", {class: ["lbh-lrow", wt ? "wait" : "", r.known === false ? "unk" : ""], title: `${fmt.stratKo(r.strategy)} (${r.strategy}) · 4시간 안 신호 최근 ${pctK(v)} · 5년 ${pctK(all)} · 1시간 안 ${pctK(r.p && r.p.w1 && r.p.w1.recent)} · 24시간 안 ${pctK(r.p && r.p.w24 && r.p.w24.recent)}${r.known === false ? " · 기준표에 없는 매매법" : ""}`},
      h("b", {class: "lbh-lrank num"}, String(r.rank)),
      h("span", {class: "lbh-lname"}, h("b", null, fmt.stratKo(r.strategy)), r.type ? h("span", {class: "lbh-ltype"}, r.type) : null,
        (r.tfs || []).length ? h("span", {class: "lbh-ltf"}, r.tfs.map((t) => fmt.tfKo(t)).join("·")) : null,
        wt ? h("span", {class: "lbh-lwait"}, `⏳ 진입 대기${wt > 1 ? ` ${fmt.int(wt)}` : ""}`) : null),
      h("span", {class: "lbh-lval"}, h("b", {class: "num"}, r.known === false ? "기준 없음" : pctK(v)), h("small", {class: "num"}, `5년 ${pctK(all)}`)),
      h("span", {class: "lbh-lbar", "aria-hidden": "true"}, h("i", {style: {transform: `scaleX(${v == null ? 0 : Math.max(0, Math.min(1, Number(v) / scale)).toFixed(3)})`}})));
  });
  return h("div", {class: "lbh-lcard"}, head,
    rows.length ? h("ol", {class: "lbh-llist"}, rows) : h("p", {class: "lbh-wnone"}, "순위를 낼 매매법이 없어요"),
    foot, lk.note_ko ? h("p", {class: "lbh-wnote"}, lk.note_ko) : null);
}

// ================================================================ the ring of strategies (canvas)
/**
 * orbView(ctx) -> {el, set({groups, hold, hot, spin, compact}), stream(code, sym, tone)}: the particle torus. groups:
 * [{code, settings, lvl}] (tilesOf), hold: the code holding the position, hot: a coin to light (the last signal's or the
 * position's), spin: the paper bot's record is fresh (the ring turns only then). A frame at most every 33 ms, the canvas
 * at the box's size x devicePixelRatio (2 at most), nothing drawn on a hidden page or after the screen is left; under
 * reduced motion one still frame per change. Colours: the skin's tokens, read when the screen is drawn.
 */
function orbView(ctx) {
  // two canvases: the still layer (the ring's glow and the lines out to the coins: a turn about the vertical axis leaves
  // the ring's middle line where it is, so they are drawn only when the size, the colours or the lit coin change) and the
  // moving layer (the points and the streams, at most ~30 frames a second)
  // (their place is set here, not only in the css: a canvas sized before the stylesheet arrives must never grow its own box)
  const pin = {position: "absolute", left: "0", top: "0", width: "100%", height: "100%", display: "block"};
  const bgc = h("canvas", {class: "lbh-orbc lbh-orbbg", "aria-hidden": "true", style: pin});
  const cv = h("canvas", {class: "lbh-orbc", "aria-hidden": "true", style: pin});
  const g2 = cv.getContext ? cv.getContext("2d") : null;
  const gb = bgc.getContext ? bgc.getContext("2d") : null;
  const labels = Object.fromEntries(COINS.map((sym, i) => [sym, h("span", {class: ["lbh-coin", i < 3 ? "l" : "r"],
    style: {left: `${COIN_AT[i][0]}%`, top: `${COIN_AT[i][1]}%`}}, h("i", {"aria-hidden": "true"}), fmt.coin(sym))]));
  const legend = h("p", {class: "lbh-orbleg"});
  const box = h("div", {class: "lbh-orbbox", style: {position: "relative", overflow: "hidden"}}, bgc, cv, ...Object.values(labels));
  const el = h("div", {class: "lbh-orb", role: "img", "aria-label": "매매법 고리: 점 묶음 하나가 매매법 하나, 밝을수록 이번 주 신호가 많아요"}, box, legend);
  const o = {groups: [], arcs: [], pts: [], hold: null, holdG: -1, hot: null, spin: false, angle: 0.9, streams: [], W: 0, H: 0, dpr: 1, sc: 1, cx: 0, cy: 0,
    raf: 0, last: 0, col: null, sig: "", alive: true};
  const tok = () => {
    const cs = getComputedStyle(document.documentElement), v = (k) => String(cs.getPropertyValue(k) || "").trim();
    o.col = {cold: v("--term-cyan") || v("--accent"), hot: v("--series-core") || v("--accent"), hold: v("--warn"), hi: v("--accent-hi"), line: v("--accent"), dim: v("--muted"), up: v("--up")};
  };
  const reduced = () => motion.reduced();
  const running = () => o.alive && cv.isConnected && !document.hidden && !reduced() && !!g2 && (o.spin || o.streams.length > 0 || o.holdG >= 0);
  function layout() {
    const r = box.getBoundingClientRect ? box.getBoundingClientRect() : {width: 0, height: 0};
    let dpr = Math.min(2, (typeof window !== "undefined" && window.devicePixelRatio) || 1);
    if (r.width * r.height * dpr * dpr > MAX_PX) dpr = Math.max(1, Math.sqrt(MAX_PX / Math.max(1, r.width * r.height)));
    const W = Math.round(Math.min(r.width, 1600) * dpr), H = Math.round(Math.min(r.height, 900) * dpr);
    if (W === o.W && H === o.H && dpr === o.dpr) return false;
    o.W = W; o.H = H; o.dpr = dpr;
    cv.width = bgc.width = Math.max(1, W); cv.height = bgc.height = Math.max(1, H);
    const fit = fitRing(W, H, r.width < 520 ? 0.62 : 0.68, 0.88);
    o.sc = fit.sc; o.cx = fit.cx; o.cy = fit.cy;
    const n = r.width < 520 ? 900 : r.width < 900 ? 1400 : 2000;
    if (n !== o.n) { o.n = n; o.pts = torusPoints(o.arcs, n); }
    return true;
  }
  const anchor = (sym) => {
    const i = COINS.indexOf(sym);
    if (i < 0) return [o.cx, o.cy];
    return [(i < 3 ? 0.13 : 0.87) * o.W, (COIN_AT[i][1] / 100) * o.H];
  };
  const toScreen = (p) => [o.cx + p[0] * o.sc, o.cy - p[1] * o.sc];
  function arcPoint(gi) {
    const a = o.arcs[gi];
    if (!a) return [o.cx, o.cy + o.sc * 0.4];
    const [x, y, z] = torusXYZ((a.a0 + a.a1) / 2, Math.PI / 2);
    return toScreen(project(x, y, z, o.angle));
  }
  function drawBg() {
    if (!gb || !o.W || !o.col) return;
    const c = o.col, W = o.W, H = o.H, dpr = o.dpr;
    gb.setTransform(1, 0, 0, 1, 0, 0);
    gb.clearRect(0, 0, W, H);
    // the lines from the ring out to the coins (the coin of the last signal / the position lit)
    gb.globalCompositeOperation = "source-over";
    gb.lineWidth = Math.max(1, dpr * 0.8);
    for (const sym of COINS) {
      const e = anchor(sym), i = COINS.indexOf(sym), left = i < 3;
      const s0 = [o.cx + (left ? -1 : 1) * o.sc * 1.38, o.cy + (e[1] - o.cy) * 0.3];
      gb.globalAlpha = sym === o.hot ? 0.75 : 0.22;
      gb.strokeStyle = sym === o.hot ? c.hold : c.line;
      gb.beginPath();
      gb.moveTo(s0[0], s0[1]);
      gb.quadraticCurveTo((s0[0] + e[0]) / 2, e[1], e[0], e[1]);
      gb.stroke();
    }
    // the ring's body: a soft glow along its middle line (two wide faint strokes)
    gb.strokeStyle = c.cold;
    for (const [lw, al] of [[TUBE * 2.4, 0.05], [TUBE * 1.1, 0.06]]) {
      gb.lineWidth = lw * o.sc;
      gb.globalAlpha = al * (o.spin ? 1 : 0.5);
      gb.beginPath();
      for (let u = 0; u <= 360; u += 8) {
        const [x, y, z] = torusXYZ(u, 0, 1, 0);
        const q = project(x, y, z, 0);
        if (u) gb.lineTo(o.cx + q[0] * o.sc, o.cy - q[1] * o.sc); else gb.moveTo(o.cx + q[0] * o.sc, o.cy - q[1] * o.sc);
      }
      gb.stroke();
    }
    gb.globalAlpha = 1;
  }
  function draw(t) {
    if (!g2 || !o.W || !o.col) return;
    const c = o.col, W = o.W, H = o.H, dpr = o.dpr;
    g2.setTransform(1, 0, 0, 1, 0, 0);
    g2.clearRect(0, 0, W, H);
    g2.globalCompositeOperation = "lighter";
    // the points: brightness by the strategy's signals, the position's strategy pulsing, nearer = bigger and brighter
    const pulse = 0.62 + 0.38 * Math.sin((t || 0) / 260);
    const dim = o.spin ? 1 : 0.45;
    let gPrev = -1, base = 0;
    const cr = Math.cos(o.angle), sr = Math.sin(o.angle), ct = Math.cos(TILT), st = Math.sin(TILT);
    for (const p of o.pts) {
      if (p.g !== gPrev) {
        gPrev = p.g;
        const gr = o.groups[p.g] || {};
        const hold = p.g === o.holdG;
        g2.fillStyle = hold ? c.hold : gr.lvl != null && gr.lvl >= 3 ? c.hot : c.cold;
        base = (hold ? pulse : glowOf(gr.lvl)) * dim;
      }
      const x1 = p.x * cr - p.z * sr, z1 = p.x * sr + p.z * cr;
      const y2 = p.y * ct + z1 * st, z2 = -p.y * st + z1 * ct, k = CAM / (CAM + z2);
      const f = Math.max(0, Math.min(1, (1.45 - z2) / 2.9));
      const sz = (1 + 1.9 * f) * dpr * (o.sc > 110 * dpr ? 1.1 : 0.85);
      g2.globalAlpha = Math.min(1, (0.22 + 0.78 * f) * base);
      g2.fillRect(o.cx + x1 * k * o.sc - sz / 2, o.cy - y2 * k * o.sc - sz / 2, sz, sz);
    }
    // streams: a real new signal or entry, from its strategy's arc to its coin
    const now = t || 0;
    o.streams = o.streams.filter((s) => now - s.t0 < STREAM_MS + 900);
    for (const s of o.streams) {
      const s0 = arcPoint(s.g), e = anchor(s.sym), cpt = [(s0[0] + e[0]) / 2, Math.min(s0[1], e[1]) - o.sc * 0.35];
      const prog = Math.min(1, (now - s.t0) / STREAM_MS);
      g2.globalCompositeOperation = "source-over";
      g2.globalAlpha = 0.35 * (1 - Math.max(0, (now - s.t0 - STREAM_MS) / 900));
      g2.strokeStyle = s.color;
      g2.lineWidth = dpr;
      g2.beginPath();
      g2.moveTo(s0[0], s0[1]);
      for (let i = 1; i <= 24; i++) { const q = bezier(s0, cpt, e, (i / 24) * prog); g2.lineTo(q[0], q[1]); }
      g2.stroke();
      g2.globalCompositeOperation = "lighter";
      g2.fillStyle = s.color;
      for (let j = 0; j < 14; j++) {
        const q = prog - j * 0.035;
        if (q < 0 || q > 1) continue;
        const [x, y] = bezier(s0, cpt, e, q);
        const sz = (2.6 - j * 0.12) * dpr;
        g2.globalAlpha = Math.max(0, 1 - j / 14);
        g2.fillRect(x - sz / 2, y - sz / 2, sz, sz);
      }
    }
    g2.globalAlpha = 1;
    g2.globalCompositeOperation = "source-over";
  }
  function frame(t) {
    o.raf = 0;
    if (!running()) return;
    if (t - o.last >= FRAME_MS) {
      const dt = o.last ? Math.min(120, t - o.last) : 0;
      o.last = t;
      if (o.spin) o.angle += dt * SPIN;
      draw(t);
    }
    o.raf = requestAnimationFrame(frame);
  }
  const kick = () => { if (!o.raf && running()) { o.last = 0; o.raf = requestAnimationFrame(frame); } };
  const still = () => { if (layout()) drawBg(); draw(typeof performance !== "undefined" ? performance.now() : 0); };
  const redraw = () => { if (running()) kick(); else still(); };
  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => { if (layout()) { drawBg(); redraw(); } });
    ro.observe(box);
    ctx.track(() => ro.disconnect());
  }
  ctx.listen(document, "visibilitychange", () => { if (!document.hidden) { tok(); drawBg(); redraw(); } });
  ctx.track(() => { o.alive = false; if (o.raf) cancelAnimationFrame(o.raf); o.raf = 0; });
  requestAnimationFrame(() => { tok(); layout(); drawBg(); redraw(); });

  return {
    el,
    set(x) {
      const real = !!(x.groups && x.groups.length);
      const groups = real ? x.groups : [{code: null, settings: 1, lvl: null}];
      const sig = JSON.stringify(groups.map((g) => [g.code, g.settings]));
      if (sig !== o.sig) { o.sig = sig; o.arcs = arcsOf(groups); o.pts = torusPoints(o.arcs, o.n || 1200); }
      o.groups = groups;
      o.holdG = x.hold ? groups.findIndex((g) => g.code === x.hold) : -1;
      o.spin = !!x.spin;
      o.hot = x.hot || null;
      el.classList.toggle("compact", !!x.compact);
      el.dataset.spin = o.spin ? "1" : "";
      for (const [sym, lb] of Object.entries(labels)) lb.classList.toggle("hot", sym === o.hot);
      const nS = groups.length, nSet = groups.reduce((a, g) => a + (Number(g.settings) || 0), 0);
      legend.textContent = real ? `고리 = 매매법 ${fmt.int(nS)}개${nSet ? ` · 설정 ${fmt.int(nSet)}개` : ""} (점 묶음 하나가 매매법 하나) · 금색일수록 이번 주 신호 많음${o.holdG >= 0 ? " · 주황 = 지금 포지션" : ""}${o.spin ? "" : " · 페이퍼 기록이 새로 오지 않아 멈춰 있어요"}`
        : "매매법 정보를 불러오는 중";
      const resized = layout();
      const bsig = `${o.hot}|${o.spin}`;
      if (resized || bsig !== o.bsig) { o.bsig = bsig; drawBg(); }
      if (!o.raf) redraw();
    },
    /** A real new signal (tone "sig") or entry ("entry"): particles stream from the strategy's arc to the coin. */
    stream(code, sym, tone) {
      if (reduced() || document.hidden || !COINS.includes(sym)) return;
      const gi = code ? o.groups.findIndex((g) => g.code === code) : -1;
      o.streams.push({g: gi, sym, t0: typeof performance !== "undefined" ? performance.now() : 0, color: tone === "entry" ? o.col && o.col.hi : o.col && o.col.hot});
      if (o.streams.length > 6) o.streams.shift();
      kick();
    },
  };
}

// ================================================================ the view
/** hqView(ctx, hub) -> {el, set(d, state), alarm(list)}; hub: livebots.js {state(), at(), retry(), get()}. */
export function hqView(ctx, hub) {
  const st = {d: hub && hub.get ? hub.get() : null, state: "loading", pick: null, ms: {}, feedSeen: null};

  // ---- small builders
  const panel = (title, cls, sub, ...kids) => {
    const slot = h("div", {class: "lbh-slot"});
    const body = h("div", {class: "lbh-pb"}, ...kids);
    const h2 = h("h2", null, title);
    const subEl = sub ? h("span", {class: "lbh-phs"}, sub) : null;
    const el = h("section", {class: ["lbh-p", cls], "aria-label": title}, h("header", {class: "lbh-ph"}, h2, subEl), slot, body);
    return {el, slot, body, h2, sub: subEl};
  };
  /** One polled source of this tab: keeps its last answer; a failed refresh dims its panels and says how old it is. */
  const feed = (path, draw, panels) => {
    const f = {d: null, at: 0, err: null, busy: false};
    f.load = async () => {
      if (f.busy) return;
      f.busy = true;
      try {
        const d = await ctx.api(path);
        if (!ctx.alive()) return;
        f.d = d; f.at = serverNow(); f.err = null;
        for (const p of panels()) { put(p.slot); ui.dim(p.body, false); }
        draw();
      } catch (e) {
        if (!ctx.alive() || (e && e.name === "AbortError")) return;
        f.err = e;
        // the first panel carries the retry; the others of the same answer say how old they are (or draw their own
        // '불러오지 못했어요' when there is no answer yet)
        panels().forEach((p, i) => {
          if (f.d) { put(p.slot, ui.staleNote(e, f.at, i ? null : () => f.load())); ui.dim(p.body, true); }
          else if (!i) put(p.slot, ui.errorBox(e, () => f.load()));
        });
        draw();
        throw e;
      } finally { f.busy = false; }
    };
    return f;
  };
  const cd = (until) => h("b", {class: "num lbh-cd", dataset: {until}}, clockOf((until - serverNow()) / 1000));

  // ---- the status line: LIVE · DAY n · the verdict · the clock
  const sLive = h("span", {class: "lbh-live"}, h("i", {"aria-hidden": "true"}), h("b", null, "LIVE TRADE"));
  const sDay = h("span", {class: "lbh-dayt"});
  const sSum = h("span", {class: "lbh-sum"});
  const sNames = h("span", null, execsKo());
  const vHead = h("b", {class: "lbh-vh"}, "불러오는 중");
  const vSub = h("span", {class: "lbh-vs"});
  const verdict = h("div", {class: "lbh-verdict", role: "status"}, h("i", {class: "lbh-vdot", "aria-hidden": "true"}), h("div", {class: "lbh-vt"}, vHead, vSub));
  const clockT = h("b", {class: "num"}, "—");
  const cmd = h("div", {class: "lbh-cmd"},
    h("div", {class: "lbh-caps"}, sLive, h("span", {class: "lbh-sep", "aria-hidden": "true"}, "·"), sDay, h("span", {class: "lbh-sep", "aria-hidden": "true"}, "·"),
      sNames, sSum),
    verdict, h("div", {class: "lbh-clock", "aria-label": "한국 시간"}, clockT, h("span", null, "KST · 한국 시간")));
  const banner = h("div", {class: "lbh-banner", role: "status", hidden: true});

  // ---- reactors (the third executor's when it comes: addReactors)
  const R = Object.fromEntries(execsNow().map((id) => [id, reactor(id)]));
  /** One account's card; o: {name, aria, cls, third} for the cards that are not an executor's (딥코인 설치 전, 믹스 봇). */
  function reactor(id, o = {}) {
    const led = h("i", {class: "lbh-led", "aria-hidden": "true"});
    const ledKo = h("b", {class: "lbh-ledko"}, "불러오는 중");
    const ledSub = h("span", {class: "lbh-ledsub"});
    const segs = s("g", {class: "lbh-segs"});
    const track = s("g", {class: "lbh-trk"});
    const svg = s("svg", {class: "lbh-ring", viewBox: "0 0 200 200", "aria-hidden": "true"},
      s("circle", {class: "lbh-orbit", cx: 100, cy: 100, r: 97}), s("circle", {class: "lbh-inner", cx: 100, cy: 100, r: 73}), track, segs);
    const day = h("span", {class: "lbh-day"});
    const cur = h("span", {class: "lbh-cur"}, "$");
    const wal = h("b", {class: "lbh-wal num"}, "—");
    const mult = h("span", {class: "lbh-mult num"});
    const delta = h("span", {class: "lbh-delta num"});
    const cin = h("div", {class: "lbh-cin"}, day, h("div", {class: "lbh-wrow"}, cur, wal), mult);
    const core = h("div", {class: "lbh-core"}, svg, cin);
    const lHead = h("b", {class: "lbh-lh"}, "신호등");
    const lRule = h("span", {class: "lbh-lnote"});
    const kv = (k) => { const v = h("b", {class: "num"}, "—"); return [h("div", {class: "lbh-kv"}, h("span", null, k), v), v]; };
    const [todayRow, today] = kv("오늘 실현"), [posRow, pos] = kv("포지션"), [streakRow, streak] = kv(o.third || "연속 손실");
    const who = h("p", {class: "lbh-who"});
    const foll = h("p", {class: "lbh-foll"});
    const notes = h("div", {class: "lbh-notes"});
    const link = h("p", {class: "lbh-mlink"});
    const el = h("section", {class: ["lbh-p", "lbh-reactor", "lbh-x-" + id, o.cls || ""], "aria-label": o.aria || `${ACCT[id].ko} 실행기 (진짜 돈)`, dataset: {led: "wait"}},
      h("header", {class: "lbh-rh"}, led, h("h2", null, o.name || ACCT[id].ko), h("span", {class: "lbh-real"}, "진짜 돈")),
      who,
      h("div", {class: "lbh-st"}, ledKo, ledSub),
      core, delta,
      h("div", {class: "lbh-light"}, lHead, lRule),
      h("div", {class: "lbh-kvs"}, todayRow, posRow, streakRow),
      foll, notes, link);
    return {id, el, core, led, ledKo, ledSub, segs, track, day, wal, cur, mult, delta, lHead, lRule, today, pos, streak, who, foll, notes, link, asOf: null, sig: ""};
  }
  function drawRing(r, l) {
    const m = ringModel(l);
    const w = lightWords(l);
    const sig = JSON.stringify([m.segs.map((x) => x.v), m.need, w.tone]);
    r.el.dataset.light = w.tone;
    if (sig === r.sig) return;
    r.sig = sig;
    if (!m.n) {
      r.segs.replaceChildren(s("circle", {class: "lbh-seg off", cx: 100, cy: 100, r: 86}));
      r.track.replaceChildren();
      return;
    }
    r.segs.replaceChildren(...m.segs.map((x, i) => s("path", {class: ["lbh-seg", x.v == null ? "none" : x.v ? "win" : "loss", i === m.segs.length - 1 && x.v != null ? "last" : ""],
      d: arcPath(100, 100, 86, x.a0, x.a1)})));
    const kids = [s("path", {class: "lbh-tbase", d: arcPath(100, 100, 97, 0, 359.99)})];
    if (m.wins) kids.push(s("path", {class: "lbh-twin", d: arcPath(100, 100, 97, 0, m.winA)}));
    if (m.needA != null) {
      const [x0, y0] = polar(100, 100, 92, m.needA), [x1, y1] = polar(100, 100, 102, m.needA);
      kids.push(s("line", {class: "lbh-need", x1: x0.toFixed(2), y1: y0.toFixed(2), x2: x1.toFixed(2), y2: y1.toFixed(2)}));
    }
    r.track.replaceChildren(...kids);
  }
  function setReactor(r, a, x) {
    const led = ledOf(a && a.state ? a : st.d ? {state: "missing"} : null);
    if (!st.d && st.state === "failed") { led.id = "bad"; led.ko = "불러오지 못함"; led.why = null; }
    r.el.dataset.led = led.id;
    r.ledKo.textContent = led.ko;
    r.el.title = led.why ? `${ACCT[r.id].ko}: ${led.ko} · ${led.why}` : "";
    r.asOf = a && a.state === "ok" ? a.as_of_ms : null;
    r.ledSub.textContent = led.why && led.id !== "stale" ? led.why : r.asOf ? `${ageKo(r.asOf)} 기록` : "";
    const ok = !!(a && a.state === "ok");
    const dn = ok ? dayN(a.since_ms, serverNow()) : null;
    r.day.textContent = dn ? `DAY ${String(dn).padStart(2, "0")}` : "";
    r.day.title = dn && a.since_ms ? `실거래 시작 ${fmt.kst(a.since_ms)} (한국 시간 기준 ${dn}일째)` : "";
    // the wallet: the exchange balance the executor last saved (open position valued in); 수집 전 / 못 읽음, never 0
    if (ok && a.balance != null) {
      r.cur.hidden = false;
      r.wal.classList.remove("unk");
      motion.countTo(r.wal, Number(a.balance), {format: (v) => fmt.money(v), glow: true});
      const m = multOf(a);
      r.mult.textContent = m == null ? "" : `×${fmt.num(m, 2)}`;
      r.mult.className = ["lbh-mult", "num", m == null ? "" : m > 1.00499 ? "up" : m < 0.99501 ? "down" : ""].join(" ");
      r.mult.title = m == null ? "" : `첫 잔고 기록${a.initial_ts ? ` (${fmt.kst(a.initial_ts)})` : ""} ${usd0(a.initial)}의 몇 배인지 · 입출금 뺌`;
      const dv = a.initial != null ? Number(a.balance) - Number(a.initial) : null;
      r.delta.textContent = dv == null ? "" : `첫 기록 대비 ${usdS(dv)}`;
      r.delta.className = ["lbh-delta", "num", fmt.tone(dv, fmt.money(dv))].join(" ");
      r.delta.title = `거래소 잔고 (열린 포지션 평가 포함) · 첫 잔고 기록 ${usd0(a.initial)}${a.initial_ts ? ` (${fmt.kst(a.initial_ts)})` : ""} 대비, 입출금 뺌`;
    } else {
      motion.countTo(r.wal, null);
      r.cur.hidden = true;
      r.wal.textContent = !st.d ? (st.state === "failed" ? "—" : "…") : ok ? "기록 전" : led.ko;
      r.wal.classList.add("unk");
      r.mult.textContent = "";
      r.delta.textContent = ok ? "잔고 기록이 아직 없어요" : "";
      r.delta.className = "lbh-delta";
    }
    // the light: the paper's last 20 closed trades in the executor's own rule
    const l = x ? x.light : null;
    const w = lightWords(l);
    drawRing(r, l);
    r.lHead.textContent = x ? `신호등 · ${w.short}` : "신호등 —";
    r.lHead.className = ["lbh-lh", w.tone].join(" ");
    const m = ringModel(l);
    r.lRule.textContent = !x ? "" : m.n ? `기준 ${fmt.pct(m.min, 0, false)} · 최근 ${m.n}번 중 ${m.need}번 이상 이김` : w.line;
    r.lHead.title = w.line + (w.next ? ` · ${w.next}` : "");
    r.lRule.title = r.lHead.title;
    // today, position, streak
    if (!ok) {
      for (const k of [r.today, r.pos, r.streak]) { k.textContent = st.d ? (a && a.state === "error" ? "못 읽음" : "수집 전") : "—"; k.className = "muted"; }
    } else {
      const t = a.today || {};
      r.today.className = ["num", fmt.tone(t.pnl, fmt.money(t.pnl))].join(" ");
      r.today.textContent = t.trades ? `${usdS(t.pnl)} · ${fmt.int(t.trades)}번 ${fmt.int(t.wins)}승 ${fmt.int(t.losses)}패` : "닫힌 거래 없음";
      r.today.title = "오늘(한국 시간 0시부터) 닫힌 거래의 실현 손익 · 거래소 수수료·펀딩 포함";
      const p = a.position;
      r.pos.className = p ? (Number(p.side) > 0 ? "up" : "down") : "muted";
      r.pos.textContent = p ? `${fmt.coin(p.symbol)} ${fmt.sideKo(p.side)} ${fmt.lev(p.leverage)} · ${p.status === "entering" ? "진입 확인 중" : p.locked ? "잠금" : "손절 걸림"}` : "없음";
      r.pos.title = p ? `진입 ${fmt.price(p.entry)} · 거래소 손절 ${fmt.price(p.stop)}` : "한 번에 포지션 하나";
      const cl = a.consecutive_losses, mx = a.max_consecutive_losses;
      r.streak.className = "num" + (cl && mx && cl >= mx ? " down" : "");
      r.streak.textContent = cl == null ? "—" : mx ? `${fmt.int(cl)} / ${fmt.int(mx)}` : fmt.int(cl);
      r.streak.title = mx ? `${fmt.int(mx)}연패면 실행기가 멈춰요` : "";
    }
    // two paper bots (the summary's papers): the paper bot it follows by its label, else the account as before
    r.foll.textContent = x ? `따라감 · ${x.follows_ko || x.follows || "—"}${a && a.sub_ko ? ` · ${a.sub_ko}` : ""}` : "";
    whoLine(r, botOfExec(st.d, x), "따라감 · 그 봇의 페이퍼 진입을 실거래로 따라 들어가요");
    const ns = [...((x && x.notes) || [])];
    if (ok && a.kill_file && a.kill_file.present) ns.unshift(`비상 정지 파일이 있어요 (${a.kill_file.path || ""})`);
    if (ok && a.halted) ns.unshift(`멈춤: ${a.halt_reason || "이유 기록 없음"}${a.halted_ts ? ` · ${fmt.kst(a.halted_ts)}부터` : ""} · 사람이 풀 때까지 새 진입 없음`);
    // the old '친구 매매법' executor of WOO X Pro 2: the mix bot trades that account now (its unit stops this one)
    const mb = mixBot();
    if (r.id === "wooxpro2" && mb && mb.status && mb.status.state !== "off") {
      ns.push(`같은 WOO X Pro 2 계정을 지금은 ${MIX_BOT_KO}이 써요 · 이 칸은 예전 '친구 매매법' 실행기 기록이에요`);
    }
    r.notes.replaceChildren(...ns.map((t) => h("p", null, t)));
  }
  /** The card's 봇 line: which bot it is or follows, and how (never empty once the answer says it). */
  function whoLine(r, bot, how) {
    if (r.who.dataset.k === `${bot}|${how}`) return;
    r.who.dataset.k = `${bot}|${how}`;
    r.who.replaceChildren(...(bot ? [h("span", {class: "lbh-whok"}, "봇"), h("b", null, bot), h("span", {class: "lbh-whos"}, how)] : []));
  }

  // ---- 딥코인 before its executor is installed: a card that says so (no number, no ring)
  const soon = reactor("deepcoin", {cls: "lbh-soon", aria: "딥코인 실행기 (진짜 돈) · 설치 전"});
  function setSoon() {
    soon.el.dataset.led = "none";
    soon.ledKo.textContent = "설치 전";
    soon.ledSub.textContent = "이 서버에 딥코인 실행기가 아직 없어요";
    whoLine(soon, "VWAP 개선판", "따라갈 실행기 (paperbot-executor-deepcoin)");
    soon.cur.hidden = true;
    soon.wal.textContent = "설치 전";
    soon.wal.classList.add("unk");
    soon.lHead.textContent = "신호등 —";
    soon.lRule.textContent = "";
    for (const k of [soon.today, soon.pos, soon.streak]) { k.textContent = "—"; k.className = "muted"; }
    if (!soon.segs.firstChild) soon.segs.replaceChildren(s("circle", {class: "lbh-seg off", cx: 100, cy: 100, r: 86}));
    soon.foll.textContent = "실거래 · VWAP 개선판 페이퍼를 따라가요 (docs/deepcoin-ko.md)";
    if (!soon.notes.firstChild) soon.notes.replaceChildren(h("p", null, "설치하고 켜면 잔고 · 신호등 · 포지션이 여기 보여요 (그 전에는 숫자를 만들지 않아요)"));
  }

  // ---- the mix bots, each trading an account by itself (their own state and log, dash/more/livemix.py): WOO X Pro 2's
  // 친구 30분 봇(믹스) (/api/v4/livebots/mix) and, once it took the Bybit slot (owners 10-29: the summary's ``replaced``),
  // the 바이비트 봇 (/api/v4/livebots/mixbybit)
  const MIXES = MIX_BOTS.map((m) => ({...m, r: reactor(m.slot, {cls: ["lbh-mix", m.cls].filter(Boolean).join(" "), name: m.account,
    aria: `${m.account} · ${m.bot} (진짜 돈)`, third: "새 진입"}), d: null, at: 0, err: null, busy: false}));
  const MX = MIXES[0];
  /** The live bot of a mix bot's last answer (null before it, or an answer without it). */
  const liveOf = (m) => {
    const bots = m.d && Array.isArray(m.d.bots) ? m.d.bots : null;
    return bots ? bots.find((b) => b && b.id === "live") || null : null;
  };
  /** The 친구 30분 봇's live bot (the old WOO X Pro 2 executor's card says it took that account). */
  const mixBot = () => liveOf(MX);
  /** Is a mix bot's card on this server's 한눈에 (the friend bot's always, the 바이비트 봇's once it took the slot)? */
  const shownMix = (m) => !m.replaces || !!(st.d && (st.d.replaced || []).some((x) => x && x.id === m.replaces));
  async function loadMix(m) {
    if (m.busy || !shownMix(m)) return;
    m.busy = true;
    try {
      const d = await ctx.api(m.api);
      if (!ctx.alive()) return;
      m.d = d; m.at = serverNow(); m.err = null;
    } catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      m.err = e;
    } finally { m.busy = false; }
    setMix(m);
    if (st.d && m.replaces) drawCenter();               // its row in the centre's real-money strip
  }
  const setMixes = () => { for (const m of MIXES) setMix(m); };
  function setMix(m) {
    const show = shownMix(m);
    m.r.el.hidden = !show;
    if (!show) return;
    if (!m.r.el.parentNode) deck.append(m.r.el);
    const b = liveOf(m);
    const led = mixLed(b, !!m.err && !b, {ko: m.bot, unit: m.unit});
    const r = m.r;
    r.el.dataset.led = led.id;
    r.ledKo.textContent = led.ko;
    const s0 = (b && b.status) || {};
    r.asOf = (led.id === "run" || led.id === "stale") && s0.seen_ms ? s0.seen_ms : null;
    r.ledSub.textContent = led.why && led.id !== "stale" ? led.why : r.asOf ? `${ageKo(r.asOf)} 기록` : "";
    r.el.title = led.why ? `${m.account} · ${m.bot}: ${led.ko} · ${led.why}` : "";
    whoLine(r, m.bot, "스스로 매매 · 페이퍼를 따라가지 않음");
    const dn = s0.first_start_ms ? dayN(s0.first_start_ms, serverNow()) : null;
    r.day.textContent = dn ? `DAY ${String(dn).padStart(2, "0")}` : "";
    r.day.title = dn ? `처음 켬 ${fmt.kst(s0.first_start_ms)} (한국 시간 기준 ${dn}일째)` : "";
    const on = !!b && s0.state !== "off" && s0.state !== "error";
    const e = (b && b.equity) || {}, n = e.now;
    // owners 10-27 ("친구봇 돈 움직이는것도 안뜨고"): with a position open, the balance read at its entry plus the position at the
    // page's mark (before the exit fee), so the card moves like the executors' (their balance is the exchange's, position in)
    const pq = on && b.position && b.position.state === "ok" ? b.position : null;
    const mk = pq ? store.mark(pq.symbol) : null;
    const uPnl = pq && mk ? unrealized(pq, mk) : null;
    const live = uPnl != null && !!n && (n.from === "entry" || n.from === "adopted");
    if (on && n && n.value != null) {
      const val = Number(n.value) + (live ? uPnl : 0);
      r.cur.hidden = false;
      r.wal.classList.remove("unk");
      motion.countTo(r.wal, val, {format: (v) => fmt.money(v), glow: !live});
      const m = e.start > 0 ? val / Number(e.start) : null;
      r.mult.textContent = m == null ? "" : `×${fmt.num(m, 2)}`;
      r.mult.className = ["lbh-mult", "num", m == null ? "" : m > 1.00499 ? "up" : m < 0.99501 ? "down" : ""].join(" ");
      r.mult.title = m == null ? "" : `시작 잔고 ${usd0(e.start)}의 몇 배인지`;
      const dv = e.start != null ? val - Number(e.start) : null;
      r.delta.textContent = dv == null ? "" : live ? `시작 대비 ${usdS(dv)} · 진입 때 잔고 ${usd0(n.value)} + 평가 ${usdS(uPnl)}`
        : `시작 대비 ${usdS(dv)} · ${n.from_ko || "기록된 잔고"} ${fmt.kst(n.ms)}`;
      r.delta.className = ["lbh-delta", "num", fmt.tone(dv, fmt.money(dv))].join(" ");
      r.delta.title = live ? `진입 때 읽은 잔고(${fmt.kst(n.ms)})에 지금 열린 포지션의 평가 손익(마크 ${fmt.price(mk)}, 나갈 때 수수료 전)을 더한 어림값 · 정확한 값은 앱에서`
        : `봇이 ${m.exchange}에서 읽어 기록한 마지막 잔고 (켤 때 · 진입 때 · 청산 뒤) · 지금 거래소 값은 앱에서`;
    } else {
      motion.countTo(r.wal, null);
      r.cur.hidden = true;
      r.wal.textContent = !b ? (m.err ? "—" : "…") : s0.state === "off" ? "꺼짐" : s0.state === "error" ? "못 읽음" : "기록 전";
      r.wal.classList.add("unk");
      r.mult.textContent = "";
      r.delta.textContent = on ? (e.none_ko || "잔고 기록이 아직 없어요") : "";
      r.delta.className = "lbh-delta";
    }
    // the ring: its last 20 closed trades (no signal light: it enters on every 30-minute signal)
    const tr = tradeRing(on ? b.recent : null);
    const sig = JSON.stringify(tr.segs.map((x) => x.v));
    if (sig !== r.sig) {
      r.sig = sig;
      r.segs.replaceChildren(...(on && b.recent ? tr.segs.map((x, i) => s("path", {class: ["lbh-seg", x.v == null ? "none" : x.v ? "win" : "loss", i === tr.have - 1 ? "last" : ""],
        d: arcPath(100, 100, 86, x.a0, x.a1)})) : [s("circle", {class: "lbh-seg off", cx: 100, cy: 100, r: 86})]));
    }
    r.el.dataset.light = "";
    r.lHead.textContent = !on ? "최근 거래 —" : tr.have ? `최근 거래 · ${fmt.int(tr.wins)}승 ${fmt.int(tr.losses)}패` : "아직 닫힌 거래 없음";
    r.lHead.className = "lbh-lh";
    r.lRule.textContent = on ? `신호등 없음 · 30분봉 신호마다 바로 들어가요 · 칸 하나가 거래 하나 (최근 ${tr.n}번)` : "";
    if (!on) {
      for (const k of [r.today, r.pos, r.streak]) { k.textContent = !b ? "—" : s0.state === "error" ? "못 읽음" : "—"; k.className = "muted"; }
    } else {
      const t = b.today;
      r.today.className = ["num", t ? fmt.tone(t.pnl, fmt.money(t.pnl)) : "muted"].join(" ");
      r.today.textContent = !t ? "못 읽음" : t.n ? `${usdS(t.pnl)} · ${fmt.int(t.n)}번 ${fmt.int(t.wins)}승 ${fmt.int(t.losses)}패${t.unknown ? ` · 손익 모름 ${fmt.int(t.unknown)}` : ""}` : "닫힌 거래 없음";
      r.today.title = "오늘(한국 시간 0시부터) 닫힌 거래 · 손익은 진입 때부터 청산 뒤까지 잔고 변화";
      const p = b.position;
      r.pos.className = p && p.state === "ok" ? (Number(p.side) > 0 ? "up" : "down") : "muted";
      const pr = p && p.state === "ok" ? roeAt(p, store.mark(p.symbol)) : null;
      r.pos.textContent = !p ? "없음" : p.state !== "ok" ? "몰라요" : `${p.coin} ${fmt.sideKo(p.side)} ${fmt.lev(p.leverage)} · ${p.step > 0 ? `계단 ${p.step}단계` : "손절 걸림"}${pr != null ? ` · ROE ${fmt.pct(pr, 1)}` : ""}`;
      r.pos.title = p && p.state === "ok" ? `진입 ${fmt.price(p.entry)} · 손절 ${fmt.price(p.stop)}` : "한 번에 포지션 하나";
      r.streak.textContent = mixGate(b);
      r.streak.className = /멈춤|몰라요/.test(r.streak.textContent) ? "down" : /금지/.test(r.streak.textContent) ? "muted" : "";
    }
    const coins = (b && b.coins) || [];
    r.foll.textContent = b ? `30분봉 신호 · ${coins.map((c) => `${c.coin}${c.enabled ? "" : "(꺼짐)"}`).join("·") || "코인 모름"}${b.plan_short_ko ? ` · ${b.plan_short_ko}` : b.risk_pct != null ? ` · 손절 1번 잔고의 ${fmt.num(b.risk_pct, 2)}%` : ""}` : "";
    const ns = [];
    if (b && s0.state === "stopped") ns.push(led.why);
    if (b && led.id === "halt") ns.push(`새 진입 멈춤: ${led.why} · 열린 포지션은 손절·계단 그대로`);
    if (b && s0.mode_ko) ns.push(s0.mode_ko);
    for (const t of (b && b.setup_bad) || []) ns.push(`마지막 시작 때 설정 실패: ${t}`);
    const old = st.d ? by(st.d.accts, m.oldExec) : null;
    if (old && old.state === "ok" && !old.stale) ns.push(`같은 계정의 예전 ${m.oldKo} 실행기도 기록 중이에요 · 한 계정에는 봇 하나만 켜 두세요`);
    if (r.notes.dataset.k !== JSON.stringify(ns)) { r.notes.dataset.k = JSON.stringify(ns); r.notes.replaceChildren(...ns.map((t) => h("p", null, t))); }
    if (!r.link.firstChild) r.link.replaceChildren(h("a", {href: ctx.href ? ctx.href(m.tab) : `#/${m.tab}`}, m.linkKo));
  }

  // ---- milestones: a one-time burst for a real milestone first seen in this browser
  function celebrate(r, key) {
    if (motion.reduced() || !motion.visible()) return;
    const label = key === "win1" ? "첫 수익 거래!" : key === "x2" ? "×2 돌파!" : "×1.5 돌파!";
    const bits = Array.from({length: 26}, (_, i) => {
      const ang = (i / 26) * 360 + (i % 3) * 7, dist = 70 + (i % 5) * 18;
      const [x, y] = polar(0, 0, dist, ang);
      return h("i", {class: "c" + (i % 5), style: {"--dx": `${x.toFixed(1)}px`, "--dy": `${y.toFixed(1)}px`, "--rot": `${(i * 47) % 360}deg`, animationDelay: `${(i % 4) * 40}ms`}});
    });
    const burst = h("div", {class: "lbh-burst", "aria-hidden": "true"}, ...bits, h("b", {class: "lbh-flare"}, label));
    r.core.append(burst);
    setTimeout(() => burst.remove(), 2600);
  }
  function milestones(d) {
    let seen = [];
    seen = local.get(MS_KEY, []);
    if (!Array.isArray(seen)) seen = [];
    let changed = false;
    for (const id of execIds(d)) {
      const a = by(d.accts, id);
      if (!a || a.state !== "ok" || !R[id]) continue;
      const tag = `${id}|${a.since_ms || 0}|`;
      const reached = milestonesOf(a);
      const mine = seen.filter((k) => k.startsWith(tag)).map((k) => k.slice(tag.length));
      const wins = (d.fills || []).filter((f) => f.acct === id && f.kind === "exit" && Number(f.pnl) > 0).map((f) => f.t);
      const firstWinAt = a.stats && Number(a.stats.wins) === 1 && wins.length ? Math.max(...wins) : null;
      const fresh = freshMilestones(st.ms[id] || null, reached, mine, firstWinAt, serverNow());
      st.ms[id] = reached;
      for (const k of reached) if (!mine.includes(k)) { seen.push(tag + k); changed = true; }
      if (fresh.length) celebrate(R[id], fresh[fresh.length - 1]);
    }
    if (changed) local.set(MS_KEY, seen.slice(-60));
  }

  // ---- the centre: the ring of strategies over the gauge (a position) or the idle words (none)
  const gSvg = s("svg", {class: "lbh-gsvg", viewBox: "0 0 400 172", "aria-hidden": "true"});
  const gZones = s("g"), gTicks = s("g", {class: "lbh-gtk"}), gFill = s("path", {class: "lbh-gfill"}), gMarks = s("g");
  const needle = s("g", {class: "lbh-needle"}, s("path", {d: "M195 150 L200 36 L205 150 Z"}), s("circle", {cx: 200, cy: 150, r: 10}), s("circle", {class: "hub", cx: 200, cy: 150, r: 4}));
  gSvg.append(s("path", {class: "lbh-gtrack", d: arcPath(200, 150, 120, -88, 88)}), gZones, gTicks, gFill, gMarks, needle);
  for (let a = -88; a <= 88; a += 4) {
    const [x0, y0] = polar(200, 150, a % 20 === 0 ? 133 : 136, a), [x1, y1] = polar(200, 150, 140, a);
    gTicks.append(s("line", {x1: x0.toFixed(2), y1: y0.toFixed(2), x2: x1.toFixed(2), y2: y1.toFixed(2)}));
  }
  const gLabels = h("div", {class: "lbh-glabels"});
  const gBox = h("div", {class: "lbh-gbox"}, gSvg, gLabels);
  const gTitle = h("div", {class: "lbh-gt"});
  const gRoe = h("b", {class: "lbh-groe num"}, "—");
  const gRoeK = h("span", {class: "lbh-groek"});
  const gNext = h("p", {class: "lbh-gnext"});
  const gEx = h("div", {class: "lbh-gex"});
  const gauge = h("div", {class: "lbh-gauge", hidden: true}, gTitle, gBox, h("div", {class: "lbh-gread"}, gRoe, gRoeK), gNext, gEx);

  const orb = orbView(ctx);
  const iHead = h("b", {class: "lbh-ih"}, "불러오는 중");
  const iUntil = h("span", {class: "lbh-iu"});
  const iSub = h("p", {class: "lbh-isub"});
  const iSig = h("p", {class: "lbh-isig"});
  const iScope = h("p", {class: "lbh-iscope"});
  const iWait = h("p", {class: "lbh-iwait"});
  const idle = h("div", {class: "lbh-idle"}, h("div", {class: "lbh-iw"}, h("div", {class: "lbh-ihead"}, iHead, iUntil), iSub, iWait, iSig, iScope));
  const center = h("section", {class: ["lbh-center"], "aria-label": "지금 포지션 또는 대기", dataset: {mode: "idle"}}, orb.el, gauge, idle);

  // ---- the frame: the side labels, the deck, the progress bar and the ticker
  const pbFill = h("i", {class: "lbh-pbf"});
  const pbText = h("span", {class: "lbh-pbt"}, "40번 판단까지");
  const pbNum = h("b", {class: "lbh-pbn num"}, "—");
  const PB_RULE = "88% 이상 금액 늘리기 검토 · 82~88% 지켜보기 · 82% 미만 멈추고 다시 생각 · 40번 전에는 판단 안 함";
  const pbRule = h("p", {class: "lbh-pbrule"}, PB_RULE);
  const pbar = h("div", {class: "lbh-pbar", role: "progressbar", "aria-label": "40번 판단까지 페이퍼(연습) 거래 수", "aria-valuemin": "0", "aria-valuemax": "40"},
    h("div", {class: "lbh-pbh"}, h("i", {class: "lbh-pbic", "aria-hidden": "true"}), pbText, pbNum), h("div", {class: "lbh-pbtrack"}, pbFill),
    pbRule);
  const tRunA = h("div", {class: "lbh-trun"}), tRunB = h("div", {class: "lbh-trun", "aria-hidden": "true"});
  const tIn = h("div", {class: "lbh-tin"}, tRunA, tRunB);
  const ticker = h("div", {class: "lbh-ticker", role: "marquee", "aria-label": "실거래 숫자 흐름"}, tIn);
  const side = (t) => h("span", {class: "lbh-side", "aria-hidden": "true"}, t);
  const sideBot = side(sideBotKo(undefined));             // the paper bot's name from the first summary on (drawBot)
  const [first, ...rest] = execsNow();                // the first reactor · the centre · the others (as before: 바이비트 · WOO X Pro)
  const deck = h("div", {class: "lbh-deck"}, R[first].el, center, ...rest.map((id) => R[id].el));
  /** The reactors of the summary's executors: the third (딥코인) is added after the others when it comes; with three the
   *  deck puts the centre on top and the reactors in a row (livebots-hq.css .lbh-deck.three), with four (WOO X Pro 2) the
   *  four in a row (.four; a phone two a row). */
  function addReactors(ids) {
    for (const id of ids) {
      if (R[id]) continue;
      R[id] = reactor(id);
      deck.append(R[id].el);
    }
    for (const id of EXEC_SLOTS) if (R[id]) R[id].el.hidden = !ids.includes(id);
    // the four accounts always (owners 10/25 night): 딥코인's 설치 전 card until its executor comes, the mix bot's card;
    // the order is the css's (.lbh-deck > .lbh-x-*), whatever came first
    if (ids.includes("deepcoin")) { if (soon.el.parentNode) soon.el.remove(); }
    else if (!soon.el.parentNode) deck.append(soon.el);
    const n = ids.length + (ids.includes("deepcoin") ? 0 : 1) + MIXES.filter(shownMix).length;
    deck.classList.toggle("three", n > 2);
    deck.classList.toggle("four", n > 3);
    deck.classList.toggle("five", n > 4);
    deck.classList.toggle("six", n > 5);                 // 투비트 (owners 10/25) with the five: two rows of three
  }
  deck.append(soon.el, MX.r.el);                      // a mix bot that took a slot: its card once the summary says so (setMix)
  addReactors(execsNow());
  // owners 10-29 (the 추세판단 봇 switched off): no executor follows the main paper bot any more -> its 40-trade count leaves the
  // page and one line says what the centre still shows (that bot's last record)
  const retired = h("p", {class: "lbh-retired", role: "note", hidden: true},
    "추세판단 봇(페이퍼)은 따라가는 실거래가 없어요 (10/29부터 꺼 둠) · 가운데 칸은 그 봇의 지난 기록이에요");
  const frame = h("div", {class: "lbh-frame"},
    side("실거래 · LIVE · 진짜 돈 · 실거래 · LIVE"), sideBot,
    banner,
    deck,
    retired, pbar, ticker);

  // ---- the cards: ⏳ 진입 대기 · 진입 카드 · 결과 카드 · 실시간
  const wBody = h("div", {class: "lbh-wbody"});
  const waitP = panel("⏳ 진입 대기", "lbh-waitp", "신호는 나왔고 정한 가격을 기다리는 중", wBody);
  const lBody = h("div", {class: "lbh-lbody"});
  const likeP = panel(LIKELY_HEAD.table[0], "lbh-likep", LIKELY_HEAD.table[1], lBody);
  const eBody = h("div", {class: "lbh-ecard"});
  const entry = panel("진입 카드", "lbh-entry", "판정 이유까지 한눈에", eBody);
  const xBody = h("div", {class: "lbh-xcard"});
  const result = panel("결과 카드", "lbh-result", "마지막으로 닫힌 거래", xBody);
  const fList = h("ol", {class: "lbh-feed", "aria-live": "off"});
  const live = panel("실시간", "lbh-livefeed", "체결 · 경고 · 마지막 신호", fList);

  // ---- the panels below
  const whyHead = h("p", {class: "lbh-whead"}, "불러오는 중");
  const whyList = h("div", {class: "lbh-wlist"}, motion.shimmer(4));
  const whyFoot = h("div", {class: "lbh-wfoot"});
  const why = panel("왜 지금 진입 안 하나", "lbh-why", "봇이 확인하는 순서대로", whyHead, whyList, whyFoot);

  const dSvg = s("svg", {class: "lbh-dsvg", viewBox: "0 0 240 240", "aria-hidden": "true"});
  const dArcs = s("g"), dPast = s("path", {class: "lbh-dpast"}), dDots = s("g"), dHand = s("g", {class: "lbh-dhand"},
    s("line", {x1: 120, y1: 62, x2: 120, y2: 8}), s("circle", {cx: 120, cy: 12, r: 4}));
  dSvg.append(s("circle", {class: "lbh-dtrack", cx: 120, cy: 120, r: 84}), dArcs, dPast,
    ...Array.from({length: 24}, (_, i) => { const [x0, y0] = polar(120, 120, i % 6 ? 104 : 99, i * 15), [x1, y1] = polar(120, 120, 110, i * 15); return s("line", {class: i % 6 ? "lbh-dtk" : "lbh-dtk big", x1: x0.toFixed(2), y1: y0.toFixed(2), x2: x1.toFixed(2), y2: y1.toFixed(2)}); }),
    dDots, dHand);
  const dHours = h("div", {class: "lbh-dhours", "aria-hidden": "true"}, ...[0, 6, 12, 18].map((hr) => {
    const [x, y] = polar(50, 50, 26.5, hr * 15);
    return h("span", {style: {left: `${x.toFixed(2)}%`, top: `${y.toFixed(2)}%`}}, `${hr}시`);
  }));
  const dNow = h("b", {class: "lbh-dnow num"}, "—");
  const dDay = h("span", {class: "lbh-dday"});
  const dLegend = h("div", {class: "lbh-dleg"});
  const dial = panel("오늘 24시간", "lbh-dial", "한국 시간 · 쉬는 시간과 진입",
    h("div", {class: "lbh-dbox"}, dSvg, dHours, h("div", {class: "lbh-dc"}, dNow, dDay)), dLegend);

  const cSegs = s("g");
  const cSvg = s("svg", {class: "lbh-csvg", viewBox: "0 0 200 200", "aria-hidden": "true"}, s("circle", {class: "lbh-corb", cx: 100, cy: 100, r: 97}), cSegs);
  const cN = h("b", {class: "lbh-cn num"}, "—");
  const cOf = h("span", {class: "lbh-cof num"}, "/40");
  const cLeft = h("span", {class: "lbh-cleft"});
  const cRules = h("ul", {class: "lbh-crules"});
  const cNote = h("p", {class: "lbh-cnote"});
  const ckpt = panel("40번 판단까지", "lbh-ckpt", "페이퍼(연습) 닫힌 거래", h("div", {class: "lbh-cwrap"}, h("div", {class: "lbh-cbox"}, cSvg, h("div", {class: "lbh-cc"}, h("div", null, cN, cOf), cLeft)), h("div", {class: "lbh-ctext"}, cRules, cNote)));

  const waitWrap = waitP.el;
  const tGrid = h("div", {class: "lbh-tiles", role: "group", "aria-label": "매매법별 이번 주 신호"}, motion.shimmer(3, true));
  const tRead = h("div", {class: "lbh-tread", "aria-live": "polite"});
  const tLeg = h("div", {class: "lbh-tleg", "aria-hidden": "true"}, h("span", null, "신호 적음"), h("i", {class: "l0"}), h("i", {class: "l1"}), h("i", {class: "l2"}),
    h("i", {class: "l3"}), h("i", {class: "l4"}), h("span", null, "많음"), h("i", {class: "hold"}), h("span", null, "지금 포지션"));
  const tiles = panel("매매법 27개 · 이번 주 신호", "lbh-tilep", "최근 7일(한국 시간) · 밝을수록 신호가 많아요", tGrid, tRead, tLeg);
  const tHead = tiles.h2;

  const foot = h("div", {class: "lbh-foot"});
  /** The paper bot's name on the frame's side label and the footer (the 추세판단 봇's own; before the first summary none). */
  function drawBot() {
    const tb = st.d ? st.d.trend_bot || null : undefined, nm = st.d && st.d.paper ? st.d.paper.name_ko : null;
    const k = tb === undefined ? "" : paperBotKo(tb, nm);
    const names = execsKo(execIds(st.d));
    if (foot.dataset.k === k && foot.dataset.x === names && foot.firstChild) return;
    foot.dataset.k = k;
    foot.dataset.x = names;
    sideBot.textContent = sideBotKo(tb, nm);
    put(foot, ui.assumeLive(names), ui.assumeLine(["closed", "open"], `페이퍼(연습) ${k ? `${k} ` : ""}COMBO@mix · 게이지의 순ROE`));
  }
  const root = h("div", {class: "lbh", dataset: {still: ""}},
    h("h2", {class: "lbh-sr"}, "실거래 한눈에"), cmd, frame,
    h("div", {class: "lbh-cards"}, waitP.el, likeP.el, entry.el, result.el, live.el),
    h("div", {class: "lbh-row"}, why.el, dial.el, ckpt.el), tiles.el, foot);

  // ---- the sources of this tab
  let sigKey;                                         // undefined until the first /now answer: the first look is the past
  const onNow = () => {
    const ls = fNow.d && fNow.d.last_signal;
    const k = ls ? `${ls.t}|${ls.symbol}|${ls.strategy}|${ls.stage}` : null;
    if (sigKey !== undefined && k && k !== sigKey && serverNow() - ls.t < 3 * 3600000) orb.stream(ls.strategy, ls.symbol, "sig");
    if (fNow.d) sigKey = k;
  };
  const fNow = feed(NOW_API, () => { onNow(); drawWait(); drawLikely(); drawWhy(); drawStatus(); drawCenter(); drawEntry(); drawFeed(); drawTicker(); }, () => [why, waitP, likeP]);
  const fCal = feed(CAL_API, () => { drawDial(); drawStatus(); drawCenter(); drawTicker(); }, () => [dial]);
  const fRank = feed(RANK_API, () => { drawTiles(); drawCenter(); drawResult(); }, () => [tiles]);

  // ---- drawing
  function drawStatus() {
    const d = st.d, accts = (d && d.accts) || [];
    const ids = execIds(d);
    const exs = ids.map((id) => by(accts, id));
    if (sNames.textContent !== execsKo(ids)) sNames.textContent = execsKo(ids);
    const fresh = exs.some((a) => a && a.state === "ok" && !a.stale);
    sLive.dataset.on = fresh ? "1" : "";
    sLive.lastChild.textContent = fresh ? "LIVE TRADE" : d ? "실거래 기록 멈춤" : "실거래";
    sLive.title = fresh ? "실행기 기록이 몇 초 전에 들어왔어요" : "실행기 기록이 새로 들어오지 않아요";
    const days = exs.map((a) => (a && a.state === "ok" ? dayN(a.since_ms, serverNow()) : null)).filter((x) => x != null);
    sDay.textContent = days.length ? `DAY ${String(Math.max(...days)).padStart(2, "0")}` : "DAY —";
    sDay.title = days.length ? "실거래를 켠 날이 DAY 01 (한국 시간)" : "실행기 시작 기록이 아직 없어요";
    const both = exs.every((a) => a && a.state === "ok" && a.balance != null);
    sSum.textContent = both ? ` · 합계 ${usd0(exs.reduce((x, a) => x + Number(a.balance), 0))}` : "";
    sSum.title = both ? `${execsKo(ids, " + ")} 잔고 (진짜 돈만, 페이퍼 빼고)` : "";
    // the verdict: /now's own words
    const n = fNow.d;
    let tone = "wait", head = fNow.err && !n ? "지금 상태를 불러오지 못함" : "불러오는 중", until = null, untilKo = "";
    if (n) {
      const b0 = (n.items || []).find((i) => i.ok === false);
      tone = n.ready ? "ok" : !b0 ? "warn" : b0.id === "position" ? "hold" : b0.id === "weekend" || b0.id === "macro" || b0.id === "usopen" || b0.tone === "warn" ? "warn" : "stop";
      head = n.head_ko || "—";
      if (n.pause_until) { until = n.pause_until; untilKo = "다시 진입 가능까지"; }
      else if (n.next_pause && n.next_pause.from) { until = n.next_pause.from; untilKo = `다음 쉬는 시간(${n.next_pause.ko || "쉼"})까지`; }
    } else if (fCal.d && fCal.d.now && fCal.d.now.next) { until = fCal.d.now.next.from; untilKo = `다음 쉬는 시간(${fCal.d.now.next.ko || "쉼"})까지`; }
    if (mainOff(d)) { tone = "wait"; head = "추세판단 봇 꺼 둠 · 지금 실거래는 아래 계좌 카드의 봇들이 해요"; }
    verdict.dataset.tone = tone;
    vHead.textContent = head;
    vSub.replaceChildren(...(until ? [`${untilKo} `, cd(until)] : []));
    // the pause banner (weekend / a US release): the reason and when entries may start again
    const pz = pauseOf(n, fCal.d);
    banner.hidden = !pz;
    if (pz) put(banner, h("i", {class: "lbh-bic", "aria-hidden": "true"}), h("b", null, pz.ko.includes("쉬") ? pz.ko : `${pz.ko} · 진입 쉬는 중`),
      h("span", null, "신호는 계속 보지만 새 진입은 하지 않아요"), pz.until ? h("span", {class: "lbh-bcd"}, `${fmt.kst(pz.until)}까지 `, cd(pz.until)) : null);
  }

  function drawWhy() {
    const n = fNow.d;
    if (!n) { if (fNow.err) { whyHead.textContent = "왜 진입 안 하는지 불러오지 못함"; put(whyList); } return; }
    whyHead.textContent = n.head_ko || "—";
    whyHead.dataset.tone = n.ready ? "ok" : "stop";
    const row = (it) => {
      const icon = it.ok === true ? "✓" : it.ok === false ? "✕" : "?";
      const tone = it.ok === true ? "ok" : it.ok === false ? (it.id === "position" ? "hold" : it.tone === "warn" ? "warn" : "stop") : "warn";
      const det = whyDetail(it);
      return h("li", {class: ["lbh-wi", "t-" + tone], "aria-label": `${it.ok === true ? "통과" : it.ok === false ? "막힘" : "모름"}: ${it.ko}`},
        h("i", {class: "lbh-wic", "aria-hidden": "true"}, icon),
        h("span", {class: "lbh-wt"}, h("span", {class: "lbh-wk"}, it.ko),
          det ? h("span", {class: "lbh-wd"}, det.text, det.until ? [" · ", cd(det.until), " 남음"] : null) : null));
    };
    const items = n.items || [];
    const common = items.filter((i) => !i.who);
    const groups = EXEC_SLOTS.map((id) => ({id, xs: items.filter((i) => i.who === id)})).filter((g) => g.xs.length);
    put(whyList, h("ul", {class: "lbh-wul"}, common.map(row)),
      groups.length ? h("div", {class: "lbh-wex"}, groups.map((g) => h("div", {class: ["lbh-wg", "lbh-x-" + g.id]},
        h("b", {class: "lbh-wgh"}, h("i", {class: "sw", "aria-hidden": "true"}), ACCT[g.id].ko, h("span", {class: "lbh-real sm"}, "진짜 돈")), h("ul", {class: "lbh-wul"}, g.xs.map(row))))) : null);
    const ls = n.last_signal;
    const np = n.next_pause;
    put(whyFoot,
      h("p", null, h("span", {class: "k"}, "마지막 신호"), ls ? `${fmt.coin(ls.symbol)} ${fmt.sideKo(ls.side)} · ${stratName(ls.strategy)} ${fmt.tfKo(ls.tf)} · ${ls.ko || ls.stage || ""} · ${ageKo(ls.t)}`
        : n.signals && n.signals.state && n.signals.state !== "ok" ? `${n.signals.state === "error" ? "못 읽음" : "수집 전"}${n.signals.reason_ko ? ` (${n.signals.reason_ko})` : ""}` : "아직 없음"),
      np ? h("p", null, h("span", {class: "k"}, "다음 쉬는 시간"), `${np.ko || "쉼"} · ${fmt.kst(np.from)} ~ ${fmt.kst(np.to)} · `, cd(np.from), " 남음") : null);
  }

  function leadPos() {
    const accts = (st.d && st.d.accts) || [];
    const pa = by(accts, "paper");
    const pp = pa && pa.state === "ok" ? pa.position : null;
    const lives = execIds(st.d).map((id) => by(accts, id)).filter((a) => a && a.state === "ok" && a.position);
    return {lead: pp ? {p: pp, kind: "paper", a: pa} : lives.length ? {p: lives[0].position, kind: "live", a: lives[0]} : null, lives, pa};
  }
  function drawCenter() {
    const {lead, lives} = leadPos();
    gauge.hidden = !lead;
    idle.hidden = !!lead;
    center.dataset.mode = lead ? "pos" : "idle";
    const rk = fRank.d, d = st.d;
    const ls = fNow.d && fNow.d.last_signal;
    const w0 = fNow.d && fNow.d.pending && fNow.d.pending.state === "ok" && (fNow.d.pending.waits || [])[0];
    orb.set({groups: rk && rk.combo && rk.combo.state === "ok" ? tilesOf(rk).map((t) => ({code: t.code, settings: t.settings, lvl: t.lvl})) : [],
      hold: lead && lead.kind === "paper" ? lead.p.strategy_id : null, hot: lead ? lead.p.symbol : w0 ? w0.symbol : ls ? ls.symbol : null,
      spin: !!(d && d.paper && d.paper.state === "ok" && !d.paper.stale), compact: !!lead});
    if (lead) drawGauge(lead, lives);
    else drawIdle();
  }

  let gSig = "";
  function drawGauge(lead, lives) {
    const {p, kind} = lead;
    const mark = store.mark(p.symbol);
    const ladder = st.d && st.d.paper ? st.d.paper.ladder : null;
    const m = gaugeModel(p, {kind, mark, ladder});
    if (!m) return;
    const sig = JSON.stringify([kind, p.key, m.anchors.map((a) => [a.k, a.v]), p.locked, lives.map((a) => [a.id, a.position.stop])]);
    if (sig !== gSig) {
      gSig = sig;
      gZones.replaceChildren(...m.zones.filter((z) => z.a1 > z.a0).map((z) => s("path", {class: ["lbh-gz", z.tone], d: arcPath(200, 150, 120, z.a0, z.a1)})));
      gMarks.replaceChildren(...m.anchors.map((a) => {
        const [x0, y0] = polar(200, 150, 108, a.angle), [x1, y1] = polar(200, 150, 132, a.angle);
        return s("line", {class: ["lbh-gm", a.k, a.k === "stop" && a.locked ? "locked" : ""], x1: x0.toFixed(2), y1: y0.toFixed(2), x2: x1.toFixed(2), y2: y1.toFixed(2)});
      }));
      gLabels.replaceChildren(...m.anchors.map((a) => {
        const [x, y] = polar(200, 150, 150, a.angle);
        const name = a.k === "stop" ? (a.locked ? "잠금선" : "손절") : a.k === "entry" ? "진입" : a.k === "next" ? (p.locked ? "다음 잠금" : "잠금 시작") : "그다음";
        return h("span", {class: ["lbh-gl", a.k, a.angle < -24 ? "l" : a.angle > 24 ? "r" : "c", a.k === "stop" && a.locked ? "locked" : ""],
          style: {left: `${(x / 4).toFixed(2)}%`, top: `${((y / 172) * 100).toFixed(2)}%`},
          title: `${name} · ${kind === "paper" ? "순ROE" : "ROE"} ${fmt.pct(a.v, 1)} · 가격 ${fmt.price(a.price)}${a.lock != null ? ` · 여기 닿으면 ${fmt.pct(a.lock, 0, false)} 잠금` : ""}`},
        h("b", null, name), h("span", {class: "num"}, a.k === "entry" ? fmt.price(a.price) : fmt.pct(a.v, a.k === "stop" ? 1 : 0)));
      }));
      // the real stops on the exchanges, on the same scale (the executors' own stop orders)
      for (const r of lives) {
        const q = r.position;
        if (q.symbol !== p.symbol || Number(q.side) !== Number(p.side) || !(q.stop > 0)) continue;
        const ang = stepAngle(kind === "paper" ? netRoe(p, q.stop) : roeAt(p, q.stop), m.xs);
        if (ang == null) continue;
        const [x0, y0] = polar(200, 150, 96, ang), [x1, y1] = polar(200, 150, 113, ang);
        gMarks.append(s("line", {class: ["lbh-gx", "lbh-x-" + r.id], x1: x0.toFixed(2), y1: y0.toFixed(2), x2: x1.toFixed(2), y2: y1.toFixed(2)}));
        const [lx, ly] = polar(200, 150, 82, ang);
        gLabels.append(h("span", {class: ["lbh-gxl", "lbh-x-" + r.id], style: {left: `${(lx / 4).toFixed(2)}%`, top: `${((ly / 172) * 100).toFixed(2)}%`},
          title: `${ACCT[r.id].ko} 거래소 손절 ${fmt.price(q.stop)}`}, ACCT[r.id].s));
      }
      put(gTitle, h("b", {class: "lbh-gsym"}, fmt.coin(p.symbol)), h("b", {class: ["lbh-gside", Number(p.side) > 0 ? "up" : "down"]}, fmt.sideKo(p.side)),
        h("b", {class: "lbh-glev num"}, fmt.lev(p.leverage)),
        p.locked ? ui.pill(`잠금 중${p.lock_roe != null ? ` ${fmt.pct(p.lock_roe, 0, false)}` : ""}`, "good", "잠금선에서 닫히면 이익으로 끝나요") : ui.pill("손절 걸림", "warn", "아직 잠금 전: 손절선에서 닫히면 손실"),
        h("span", {class: "lbh-gwho"}, kind === "paper" ? `${stratName(p.strategy_id)}${p.timeframe ? ` · ${fmt.tfKo(p.timeframe)}` : ""} · ${fmt.hm(p.entry_time)} 진입` : `${ACCT[lead.a.id].ko} 포지션 · 페이퍼엔 없음`));
    }
    // the needle: the live mark (the dashboard's ticker) through the ladder's formula; else the paper's own last minute
    const nd = m.needle == null ? m.entryA : m.needle;
    needle.style.transform = `rotate(${(nd || 0).toFixed(2)}deg)`;
    needle.classList.toggle("unk", m.roe == null);
    const tone = m.roe == null ? "" : m.roe > 0 ? "up" : m.roe < 0 ? "down" : "";
    if (m.entryA != null && m.needle != null) {
      gFill.setAttribute("d", arcPath(200, 150, 120, Math.min(m.entryA, m.needle), Math.max(m.entryA, m.needle)));
      gFill.setAttribute("class", ["lbh-gfill", tone].join(" "));
    } else gFill.setAttribute("d", "");
    center.dataset.tone = tone;
    if (m.roe == null) motion.countTo(gRoe, null);
    else motion.countTo(gRoe, m.roe, {format: "pct", dec: 1, tone: true});
    gRoeK.textContent = `${kind === "paper" ? "순ROE · 수수료·펀딩 뺌, 잠금 계산과 같은 식" : "ROE · 나갈 때 수수료 전"} · ${mark ? `마크 ${fmt.price(mark)}` : p.last_mark ? `마지막 마크 ${fmt.price(p.last_mark)}` : "마크 가격 없음"}`;
    const nx = p.next_lock;
    gNext.textContent = nx && nx.at != null ? `다음 잠금: 순ROE ${fmt.pct(nx.at, 0, false)}${nx.price ? ` (${fmt.price(nx.price)})` : ""}에 닿으면 ${fmt.pct(nx.lock, 0, false)}로 잠가요${nx.from === "paper" ? " · 페이퍼 기준" : ""}` : "";
    // the real money: each executor's own position and its stop order on the exchange
    gEx.replaceChildren(...[...execIds(st.d).map((id) => {
      const a = by((st.d && st.d.accts) || [], id);
      const head = h("span", {class: ["lbh-gexn", "lbh-x-" + id]}, h("i", {class: "sw", "aria-hidden": "true"}), ACCT[id].ko);
      if (!a || a.state !== "ok") return h("div", {class: "lbh-gexr unk"}, head, h("span", null, a && a.state === "error" ? "못 읽음" : "수집 전"));
      const q = a.position;
      if (!q) return h("div", {class: "lbh-gexr none"}, head, h("span", null, a.halted ? "포지션 없음 · 멈춤" : "포지션 없음"));
      const r = roeAt(q, store.mark(q.symbol));
      return h("div", {class: "lbh-gexr"}, head,
        h("span", null, `${fmt.coin(q.symbol)} ${fmt.sideKo(q.side)} · 진입 `, h("b", {class: "num"}, fmt.price(q.entry))),
        h("span", null, "거래소 손절 ", h("b", {class: ["num", q.locked ? "up" : ""]}, fmt.price(q.stop)), q.locked ? " 잠금" : ""),
        r != null ? h("b", {class: ["num", "lbh-gexroe", fmt.tone(r, fmt.pct(r, 1))]}, fmt.pct(r, 1)) : null);
    }), ...MIXES.map(mixExRow)].filter(Boolean));
  }
  /** A mix bot's row in the strip (WOO X Pro 2's friend bot, owners 10-27; the 바이비트 봇, 10-29): it trades by itself, so
   *  it is not one of the executors. */
  function mixExRow(m) {
    const b = shownMix(m) ? liveOf(m) : null;
    if (!b) return null;
    const s0 = b.status || {};
    const head = h("span", {class: ["lbh-gexn", "lbh-x-" + m.slot], title: `${m.account} · ${m.bot}`}, h("i", {class: "sw", "aria-hidden": "true"}), m.account);
    if (s0.state === "off" || s0.state === "error") return h("div", {class: "lbh-gexr unk"}, head, h("span", null, s0.state === "off" ? "꺼짐" : "못 읽음"));
    const q = b.position;
    if (!q) return h("div", {class: "lbh-gexr none"}, head, h("span", null, "포지션 없음"));
    if (q.state !== "ok") return h("div", {class: "lbh-gexr unk"}, head, h("span", null, "포지션 몰라요"));
    const r = roeAt(q, store.mark(q.symbol));
    return h("div", {class: "lbh-gexr"}, head,
      h("span", null, `${fmt.coin(q.symbol)} ${fmt.sideKo(q.side)} · 진입 `, h("b", {class: "num"}, fmt.price(q.entry))),
      h("span", null, "거래소 손절 ", h("b", {class: ["num", q.locked ? "up" : ""]}, fmt.price(q.stop)), q.locked ? ` 계단 ${q.step}단계` : ""),
      r != null ? h("b", {class: ["num", "lbh-gexroe", fmt.tone(r, fmt.pct(r, 1))]}, fmt.pct(r, 1))
        : h("b", {class: "num lbh-gexroe muted", title: "이 코인의 시세가 사이트에 없어요"}, "—"));
  }

  function drawIdle() {
    const w = idleWords(st.d, fCal.d);
    center.dataset.tone = w.tone;
    iHead.textContent = w.head;
    iHead.dataset.tone = w.tone;
    put(iUntil, w.until ? [cd(w.until), " 남음"] : null);
    const n = fNow.d;
    iSub.textContent = w.sub || (n && !n.ready && n.head_ko ? n.head_ko : "");
    const off = mainOff(st.d);
    const ws = (!off && n && n.pending && n.pending.state === "ok" && n.pending.waits) || [];
    put(iWait, ws.length ? [h("span", {class: "k"}, `⏳ 진입 대기 ${fmt.int(ws.length)}개`), ws.slice(0, 2).map((w) => `${fmt.coin(w.symbol)} ${fmt.sideKo(w.side)} · ${waitWords(w).move || "기준가 못 읽음"}`).join(" / ")] : null);
    const ls = !off && n && n.last_signal;
    put(iSig, ls ? [h("span", {class: "k"}, "마지막 신호"), `${fmt.coin(ls.symbol)} ${fmt.sideKo(ls.side)} · ${stratName(ls.strategy)} ${fmt.tfKo(ls.tf)} · ${ls.ko || ""} · ${ageKo(ls.t)}`] : null);
    const rk = fRank.d;
    iScope.textContent = rk && rk.n_strategies ? `매매법 ${fmt.int(rk.n_strategies)}개 · 설정 ${fmt.int(rk.n_settings)}개가 코인 6개를 봉마다 살펴요` : "코인 6개를 봉마다 살펴요";
  }

  // ⏳ 진입 대기: a new wait (after the first look) lights its row once
  function drawWait() {
    const n = fNow.d;
    if (!n) { put(wBody, fNow.err ? ui.empty("불러오지 못했어요") : motion.shimmer(3)); return; }
    const c = waitCard(n, fNow.at);
    put(wBody, c.el);
    const keys = new Set(c.rows.keys());
    if (st.waitSeen) for (const [k, row] of c.rows) if (!st.waitSeen.has(k)) motion.ring(row, null);
    st.waitSeen = keys;
    waitWrap.classList.toggle("has", keys.size > 0);
  }

  function drawLikely() {
    const n = fNow.d;
    const [title, sub] = LIKELY_HEAD[n && n.likely && n.likely.state === "trend" ? "trend" : "table"];
    likeP.h2.textContent = title;
    if (likeP.sub) likeP.sub.textContent = sub;
    put(lBody, !n && fNow.err ? ui.empty("불러오지 못했어요") : likelyCard(n, ctx.href ? ctx.href("livebots", "rank") : "#/livebots/rank"));
  }

  // 진입 카드: the open position in full, or the last signal and what became of it
  function drawEntry() {
    const d = st.d;
    if (!d) { put(eBody, st.state === "failed" ? ui.empty("불러오지 못했어요") : motion.shimmer(4)); return; }
    const {lead, lives, pa} = leadPos();
    if (!lead) {
      const n = fNow.d, ls = n && n.last_signal;
      put(eBody, h("p", {class: "lbh-enone"}, pa && pa.state !== "ok" ? `페이퍼 기록: ${pa.state === "error" ? "못 읽음" : "수집 전"}` : "지금 열린 포지션이 없어요"),
        ls ? h("div", {class: "lbh-esig"}, h("span", {class: "k"}, "마지막 신호와 판정"),
          h("div", {class: "lbh-ebig"}, h("b", {class: ["lbh-eside", Number(ls.side) > 0 ? "up" : "down"]}, fmt.sideKo(ls.side)), h("b", {class: "lbh-ecoin"}, fmt.coin(ls.symbol)),
            h("span", {class: "lbh-etf"}, fmt.tfKo(ls.tf))),
          h("p", null, h("b", null, stratName(ls.strategy)), ` · ${fmt.kst(ls.t)} 봉 마감`),
          h("p", {class: "lbh-ewhy"}, `판정: ${ls.ko || ls.stage || "기록 없음"}`))
          : h("p", {class: "muted"}, n ? "이번 주 신호 기록이 아직 없어요" : "마지막 신호 불러오는 중"));
      return;
    }
    const p = lead.p;
    const ladder = d.paper ? d.paper.ladder : null;
    const fl = lead.kind === "paper" ? firstLock(p, ladder) : null;
    const holders = [];
    if (lead.kind === "paper") holders.push({id: "paper", p});
    for (const a of lives) if (a.position.symbol === p.symbol && Number(a.position.side) === Number(p.side)) holders.push({id: a.id, p: a.position});
    const cols = holders.map((x) => ({...x, roe: x.id === "paper" ? (store.mark(p.symbol) ? netRoe(x.p, store.mark(p.symbol)) : x.p.last_mark_roe_net) : roeAt(x.p, store.mark(x.p.symbol))}));
    const row = (k, f) => [h("span", {class: "lbh-etk"}, k), ...cols.map((c) => h("span", {class: "lbh-etv num"}, f(c)))];
    const nx = p.next_lock;
    const step = ladder && ladder.step != null ? Number(ladder.step) : null;
    const th = afterNext(nx, ladder), two = !!(ladder && ladder.next_trigger != null);
    put(eBody,
      h("div", {class: "lbh-ebig"}, h("b", {class: ["lbh-eside", Number(p.side) > 0 ? "up" : "down"]}, fmt.sideKo(p.side)),
        h("b", {class: "lbh-ecoin"}, fmt.coin(p.symbol)), h("span", {class: "lbh-etf"}, "무기한"), h("b", {class: "lbh-elev num"}, fmt.lev(p.leverage))),
      lead.kind === "paper" ? h("p", {class: "lbh-ewhy"}, h("b", null, stratName(p.strategy_id)), p.timeframe ? ` · ${fmt.tfKo(p.timeframe)}봉` : "",
        p.member_order ? ` · 설정 ${fmt.int(p.member_order)}번` : "", p.stop_rule ? ` · 손절 규칙 ${p.stop_rule}` : "", ` · ${fmt.kst(p.entry_time)} 진입`)
        : h("p", {class: "lbh-ewhy"}, `${ACCT[lead.a.id].ko}만 들고 있는 포지션 (페이퍼에는 없음)`),
      h("div", {class: "lbh-etab", style: {"--n": String(cols.length)}},
        h("span", {class: "lbh-etk"}), ...cols.map((c) => h("span", {class: ["lbh-eth", "lbh-x-" + c.id]}, h("i", {class: "sw", "aria-hidden": "true"}), acctName(c.id))),
        ...row("진입가", (c) => fmt.price(c.p.entry)),
        ...row("손절가", (c) => `${fmt.price(c.p.stop)}${c.p.locked ? " 잠금" : ""}`),
        ...row("레버리지", (c) => fmt.lev(c.p.leverage)),
        ...row("증거금", (c) => (c.p.margin == null ? "—" : moneyOf(c.id, c.p.margin, false))),
        ...row("지금 ROE", (c) => (c.roe == null ? "—" : fmt.pct(c.roe, 1)))),
      fl ? h("div", {class: "lbh-eladder"},
        h("p", null, h("span", {class: "k"}, "첫 잠금"), `순ROE ${fmt.pct(fl.at, 0, false)} (${fmt.price(fl.atPrice)})에 닿으면 ${fmt.pct(fl.lock, 0, false)} 잠금 (${fmt.price(fl.lockPrice)})`),
        nx && nx.at != null ? h("p", null, h("span", {class: "k"}, p.locked ? "다음 단계" : "그다음"), p.locked ? `순ROE ${fmt.pct(nx.at, 0, false)} (${fmt.price(nx.price)})에 닿으면 ${fmt.pct(nx.lock, 0, false)} 잠금`
          : th ? `순ROE ${fmt.pct(th.at, 0, false)}에 닿으면 ${fmt.pct(th.lock, 0, false)} 잠금 (${two ? "그 뒤 " : ""}${fmt.pct(step, 0, false)}마다 한 단계)` : "—") : null,
        fl.rr != null ? h("p", {class: "lbh-err", title: `첫 잠금 ${fmt.pct(fl.lock, 0)}를 첫 손절의 ${fmt.pct(fl.risk, 1)}와 비교 (순ROE, 페이퍼 기준)`},
          h("span", {class: "k"}, "손익비"), h("b", {class: "num"}, `1 : ${fmt.num(fl.rr, 2)}`), ` 첫 잠금 기준 · 손절 ${fmt.pct(fl.risk, 1)} 대 첫 잠금 ${fmt.pct(fl.lock, 0)}`) : null,
        h("p", {class: "muted"}, "잠금 단계는 페이퍼 기준이고, 실행기도 페이퍼가 잠그면 거래소 손절을 같이 옮겨요"))
        : null);
  }

  // 결과 카드: the last closed live trade, else the paper's (labelled)
  let xKey = null;
  function drawResult() {
    const d = st.d;
    if (!d) { put(xBody, st.state === "failed" ? ui.empty("불러오지 못했어요") : motion.shimmer(4)); return; }
    const lc = lastClosed(d.fills);
    const readable = (d.accts || []).some((a) => a.state === "ok");
    if (!lc) {
      xKey = null;
      result.el.classList.remove("has");
      put(xBody, h("p", {class: "lbh-enone"}, readable ? "아직 닫힌 거래가 없어요" : "기록을 못 읽어 몰라요"),
        readable ? h("div", {class: "lbh-xghost", "aria-hidden": "true"}, h("span", null, "코인 · 무기한 · 배수 · 롱/숏 청산"), h("b", {class: "num"}, "±0.00%"), h("span", null, "진입가 · 청산가 · 보유 시간 · 끝난 이유")) : null,
        readable ? h("p", {class: "muted lbh-xcap"}, "첫 거래가 닫히면 여기에 거래소 손익 카드처럼 크게 보여 드려요 (실거래가 먼저, 없으면 페이퍼)") : null);
      return;
    }
    const f = lc.exit, e = lc.entry;
    const win = Number(f.pnl) > 0, loss = Number(f.pnl) < 0;
    const rk = fRank.d;
    const strat = lc.paper && rk ? ((rk.rows || []).find((r) => r.paper && r.paper.last_exit_ms === f.t) || {}).strategy : null;
    result.el.classList.add("has");
    result.el.dataset.tone = win ? "up" : loss ? "down" : "";
    put(xBody,
      h("div", {class: "lbh-xtop"}, h("span", {class: ["lbh-xex", "lbh-x-" + f.acct]}, h("i", {class: "sw", "aria-hidden": "true"}), lc.paper ? "페이퍼(연습) · 모의" : `${acctName(f.acct)} · 진짜 돈`),
        h("span", {class: "lbh-xt num"}, fmt.kst(f.t))),
      h("p", {class: "lbh-xsym"}, h("b", null, `${fmt.coin(f.symbol)}USDT`), " 무기한 ", h("span", {class: "lbh-xlev num"}, fmt.lev(f.lev)),
        h("span", {class: Number(f.side) > 0 ? "up" : "down"}, ` ${fmt.sideKo(f.side)} 청산`)),
      h("b", {class: ["lbh-xroe", "num", win ? "up" : loss ? "down" : ""]}, f.roe == null ? "—" : fmt.pct(f.roe, 2)),
      h("p", {class: ["lbh-xpnl", "num", win ? "up" : loss ? "down" : ""]}, f.pnl == null ? "손익 —" : `${moneyOf(f.acct, f.pnl)}${f.est ? " 어림" : ""}`),
      h("div", {class: "lbh-xgrid"},
        h("span", {class: "k"}, "진입가"), h("b", {class: "num"}, e ? fmt.price(e.price) : "—"),
        h("span", {class: "k"}, "청산가"), h("b", {class: "num"}, fmt.price(f.price)),
        h("span", {class: "k"}, "보유"), h("b", null, e && e.t != null ? `${fmt.dur((f.t - e.t) / 1000)} 만에` : "—"),
        h("span", {class: "k"}, "끝난 이유"), h("b", {class: win ? "up" : loss ? "down" : ""}, f.reason_ko || "청산")),
      strat ? h("p", {class: "muted"}, `매매법 ${stratName(strat)}`) : null,
      h("p", {class: "muted lbh-xcap"}, lc.paper ? `실거래는 아직 닫힌 거래가 없어 페이퍼(연습)를 보여 줘요 · ROE는 수수료·펀딩 포함 (모의)` : `ROE = 손익 ÷ 증거금 · ${f.est ? "체결 기록을 아직 못 읽어 지갑 변화로 어림" : "거래소 체결 기준, 수수료·펀딩 포함"}`));
    if (f.key !== xKey) {
      if (xKey !== null) motion.play(result.el, "lbh-shine");
      else if (!motion.reduced()) result.el.classList.add("lbh-shine1");
      xKey = f.key;
    }
  }

  // 실시간: the newest real records, new ones slide in after the first look
  const fNodes = new Map();
  function drawFeed() {
    const d = st.d;
    if (!d) { put(fList, motion.shimmer(4)); return; }
    const rows = feedRows(d, fNow.d, 8);
    if (!rows.length) { put(fList, h("li", {class: "lbh-fempty"}, (d.accts || []).some((a) => a.state === "ok") ? "아직 체결도 경고도 없어요" : "기록을 못 읽어 몰라요")); return; }
    const fresh = st.feedSeen ? rows.filter((r) => !st.feedSeen.has(r.key)) : [];
    st.feedSeen = new Set([...(st.feedSeen || []), ...rows.map((r) => r.key)]);
    const TAG = {entry: "진입", lock: "잠금", stop: "손절", exit: "청산", warn: "주의", crit: "긴급", sig: "신호"};
    fList.replaceChildren(...rows.map((r) => {
      let n = fNodes.get(r.key);
      if (!n) {
        let text;
        if (r.f) {
          const f = r.f;
          text = f.kind === "entry" ? `${acctName(f.acct)} ${fmt.coin(f.symbol)} ${fmt.sideKo(f.side)} ${fmt.lev(f.lev)} · ${fmt.price(f.price)}${f.open ? " · 지금 열림" : ""}`
            : `${acctName(f.acct)} ${fmt.coin(f.symbol)} ${fmt.sideKo(f.side)} · ${f.reason_ko || "청산"} ${f.pnl == null ? "" : moneyOf(f.acct, f.pnl)}`;
        } else if (r.e) text = `${r.e.ex_ko || acctName(r.acct)} · ${r.e.kind_ko}: ${r.e.text}`;
        else text = `${fmt.coin(r.sig.symbol)} ${fmt.sideKo(r.sig.side)} · ${stratName(r.sig.strategy)} ${fmt.tfKo(r.sig.tf)} · ${r.sig.ko || r.sig.stage || ""}`;
        const tone = r.kind === "lock" || (r.f && r.kind === "exit" && Number(r.f.pnl) > 0) ? "up" : r.kind === "stop" || r.kind === "crit" ? "down" : r.kind === "warn" ? "warn" : r.kind === "entry" ? "accent" : "";
        n = h("li", {class: ["lbh-fr", "k-" + r.kind, r.acct ? "lbh-x-" + r.acct : ""], title: `${fmt.kst(r.t)} · ${text}`},
          h("span", {class: "lbh-ft num"}, fmt.hm(r.t)), h("span", {class: ["lbh-ftag", tone]}, TAG[r.kind] || ""), h("span", {class: "lbh-fx"}, text),
          h("span", {class: "lbh-fa", dataset: {t: r.t}}, ageKo(r.t)));
        fNodes.set(r.key, n);
      }
      return n;
    }));
    for (const k of [...fNodes.keys()]) if (!rows.some((r) => r.key === k)) fNodes.delete(k);
    if (fresh.length && motion.visible() && !motion.reduced()) for (const r of fresh) motion.fillIn(fNodes.get(r.key), r.kind === "lock" ? "up" : r.kind === "stop" || r.kind === "crit" ? "down" : null);
  }

  // the ticker: the same items in two copies (the loop), each text changed in place so the scroll goes on
  let tKeys = "";
  function drawTicker() {
    const items = tickerItems(st.d, fNow.d, fCal.d);
    const keys = items.map((x) => x.k).join(",");
    const mk = (x) => h("span", {class: ["lbh-ti", x.tone || ""], dataset: {k: x.k}}, x.text);
    if (keys !== tKeys) {
      tKeys = keys;
      const run = () => items.length ? items.flatMap((x, i) => (i ? [h("i", {class: "lbh-tsep", "aria-hidden": "true"}, "◆"), mk(x)] : [mk(x)])).concat(h("i", {class: "lbh-tsep", "aria-hidden": "true"}, "◆")) : [h("span", {class: "lbh-ti"}, "불러오는 중")];
      tRunA.replaceChildren(...run());
      tRunB.replaceChildren(...run());
      const chars = items.reduce((n, x) => n + x.text.length, 0);
      tIn.style.setProperty("--tdur", `${Math.max(28, Math.round(chars * 0.32))}s`);
      ticker.classList.toggle("on", items.length > 0);
      return;
    }
    for (const run of [tRunA, tRunB]) {
      for (const x of items) {
        const el = run.querySelector(`[data-k="${x.k}"]`);
        if (el && el.textContent !== x.text) { el.textContent = x.text; el.className = ["lbh-ti", x.tone || ""].join(" "); }
      }
    }
  }

  function drawDial() {
    const c = fCal.d, now = serverNow(), d0 = kstDayStart(now);
    const arcs = c ? dayArcs(c.spans, c.items, d0) : [];
    dArcs.replaceChildren(...arcs.map((x) => s("path", {class: ["lbh-darc", x.why === "weekend" ? "wk" : x.why === "usopen" ? "us" : "mc"], d: arcPath(120, 120, 84, x.a0, x.a1)})));
    // the 추세판단 봇: its own entries only (from its start; the ones before are the bot before it's)
    const tb = st.d && st.d.trend_bot, since = tb && tb.since != null ? Number(tb.since) : null;
    const dots = dayDots(st.d ? st.d.fills : [], d0, since);
    dDots.replaceChildren(...dots.map((x) => { const [cx, cy] = polar(120, 120, 84, x.a); return s("circle", {class: ["lbh-ddot", "lbh-x-" + x.acct, x.open ? "open" : ""], cx: cx.toFixed(2), cy: cy.toFixed(2), r: 6}); }));
    dDay.textContent = fmt.date(now);
    const rows = [];
    if (!c) rows.push(h("p", {class: "muted"}, fCal.err ? "쉬는 시간 일정을 불러오지 못함" : "불러오는 중"));
    else {
      if (c.events && c.events.state !== "ok") rows.push(h("p", {class: "warn"}, `경제 발표 일정: 못 읽음${c.events.reason_ko ? ` (${c.events.reason_ko})` : ""}`));
      const today = arcs.length ? arcs.map((x) => `${x.why === "weekend" ? "주말" : x.ko || "발표"} ${fmt.hm(Math.max(x.from, d0))}~${x.to >= d0 + DAY ? "24:00" : fmt.hm(x.to)}`).join(" · ") : "없음";
      rows.push(h("p", null, h("i", {class: "sw wk", "aria-hidden": "true"}), h("i", {class: "sw mc", "aria-hidden": "true"}),
        arcs.some((x) => x.why === "usopen") ? h("i", {class: "sw us", "aria-hidden": "true"}) : null, h("span", {class: "k"}, "오늘 쉬는 시간"), today));
      const nx = c.now && c.now.next;
      if (nx) rows.push(h("p", null, h("span", {class: "k"}, "다음"), `${nx.ko || "쉼"} · ${fmt.kst(nx.from)}`));
    }
    rows.push(h("p", null, h("i", {class: "sw dot", "aria-hidden": "true"}), h("span", {class: "k"}, "오늘 진입"),
      st.d ? dayEntriesKo(dots, d0, since, dots.map((x) => acctName(x.acct))) : "—"));
    dLegend.replaceChildren(...rows);
    tickDial();
  }
  function tickDial() {
    const now = serverNow(), d0 = kstDayStart(now), a = dayAngle(now, d0);
    dHand.style.transform = `rotate(${a.toFixed(2)}deg)`;
    dPast.setAttribute("d", arcPath(120, 120, 96, 0, Math.max(0.01, a)));
    dNow.textContent = fmt.hm(now);
  }

  function drawCkpt() {
    const cp = st.d ? st.d.checkpoint : null;
    const goal = cp && cp.trades ? Number(cp.trades) : 40;
    const pa = st.d ? by(st.d.accts, "paper") : null;
    const n = cp ? Number(cp.n) || 0 : null;
    const step = 360 / goal;
    cSegs.replaceChildren(...Array.from({length: goal}, (_, i) => s("path", {class: ["lbh-cseg", n != null && i < n ? "on" : "", n != null && i === n - 1 ? "last" : ""],
      d: arcPath(100, 100, 86, i * step + 1.2, (i + 1) * step - 1.2)})));
    cOf.textContent = `/${goal}`;
    const unk = !cp ? (!st.d ? "—" : pa && pa.state === "error" ? "못 읽음" : "수집 전") : null;
    if (unk) {
      motion.countTo(cN, null);
      cN.textContent = unk;
      cN.classList.toggle("unk", !!st.d);
      cLeft.textContent = st.d && pa && pa.reason_ko ? pa.reason_ko : "";
    } else {
      cN.classList.remove("unk");
      motion.countTo(cN, n, {format: "int"});
      cLeft.textContent = cp.ready ? "도착 · 두 분이 정할 때" : `남은 ${fmt.int(cp.left)}번`;
    }
    const zone = cp && cp.ready ? cp.zone : null;
    const up = cp ? cp.up_ko : "88% 이상이면 금액 늘리기 검토", mid = cp ? cp.mid_ko : "82~88%면 그대로 지켜보기", low = cp ? cp.low_ko : "82% 미만이면 멈추고 다시 생각";
    // rule_ko: the 5-year reference (and the 88 / 82 % rule made with it) is another config's: the count only, no rule
    const rules = cp && cp.rule_ko ? [["none", cp.rule_ko]] : [["up", up], ["mid", mid], ["low", low]];
    cRules.replaceChildren(...rules.map(([k, t]) => h("li", {class: ["k-" + k, zone === k ? "on" : ""]}, t)));
    cNote.textContent = cp && cp.ready ? `최근 ${fmt.int(goal)}번 승률 ${fmt.pct(cp.last_win_rate, 1, false)} · ${cp.rule_ko ? "이 설정의 판단 기준은 아직 없어요" : "두 분이 정한 규칙으로 보는 자리예요"}` : `${fmt.int(goal)}번이 되기 전에는 승률로 판단하지 않아요 (지금 숫자는 판단 아님)`;
    // the frame's progress bar (the same count)
    const pct = n != null ? Math.min(1, n / goal) : 0;
    pbFill.style.transform = `scaleX(${pct.toFixed(4)})`;
    pbar.setAttribute("aria-valuemax", String(goal));
    if (n != null) pbar.setAttribute("aria-valuenow", String(n)); else pbar.removeAttribute("aria-valuenow");
    pbText.textContent = `${fmt.int(goal)}번 판단까지 · 페이퍼(연습) 거래`;
    // a config without the 88 / 82 % rule (the 추세판단 봇: rule_ko) never shows that rule under the bar either
    pbRule.textContent = cp && cp.rule_ko ? `${cp.rule_ko} · ${fmt.int(goal)}번 전에는 판단 안 함` : PB_RULE;
    pbNum.textContent = unk ? unk : `${fmt.int(n)}/${fmt.int(goal)} · ${fmt.pct(pct, 0, false)}`;
    pbar.classList.toggle("unk", !!unk);
    pbar.classList.toggle("done", !!(cp && cp.ready));
    const off = mainOff(st.d);                          // the 추세판단 봇 followed by no executor (owners 10-29)
    pbar.hidden = off; ckpt.el.hidden = off; retired.hidden = !off;
  }

  let tSig = "";
  function drawTiles() {
    const rk = fRank.d;
    if (!rk) { if (fRank.err) put(tGrid, ui.empty("매매법 신호를 불러오지 못했어요")); return; }
    if (!rk.combo || rk.combo.state !== "ok") {
      tHead.textContent = "매매법 · 이번 주 신호";
      put(tGrid, h("p", {class: "lbh-unk"}, ui.notYet(rk.combo && rk.combo.state === "error" ? "못 읽음" : "수집 전"), ` 합친 봇 설정: ${(rk.combo && rk.combo.reason_ko) || "아직 없어요"}`));
      put(tRead);
      return;
    }
    const ts = tilesOf(rk);
    // one tile per strategy; a strategy on two entry bars (the 추세판단 봇's 18 entries on 15 strategies) says both counts
    const nSet = ts.reduce((a, t) => a + (Number(t.settings) || 0), 0);
    tHead.textContent = rk.trend_bot && nSet > ts.length ? `매매법 ${fmt.int(ts.length)}종 · 진입 ${fmt.int(nSet)}개 · 이번 주 신호`
      : `매매법 ${fmt.int(ts.length)}개 · 이번 주 신호`;
    const sig = JSON.stringify(ts.map((t) => [t.code, t.n, t.lvl, t.hold, t.today])) + "|" + ts.map((t) => stratName(t.code)).join(",") + "|" + st.pick;
    if (sig !== tSig) {
      tSig = sig;
      tGrid.replaceChildren(...ts.map((t) => h("button", {type: "button", class: ["lbh-tile", t.lvl == null ? "unk" : "l" + t.lvl, t.hold ? "hold" : "", st.pick === t.code ? "pick" : ""],
        "aria-pressed": String(st.pick === t.code), dataset: {code: t.code},
        title: `${stratName(t.code)} (${t.code})${t.type ? ` · ${t.type}` : ""} · 이번 주 신호 ${t.n == null ? "못 읽음" : fmt.int(t.n)}${t.hold ? " · 지금 포지션" : ""}`,
        onclick: () => { st.pick = st.pick === t.code ? null : t.code; drawTiles(); }},
      h("span", {class: "lbh-tn"}, stratName(t.code)), h("b", {class: "lbh-tc num"}, t.n == null ? "?" : fmt.int(t.n)))));
    }
    const t = ts.find((x) => x.code === st.pick) || ts.find((x) => x.hold) || null;
    if (!t) {
      put(tRead, h("p", {class: "muted"}, rk.signals && rk.signals.state !== "ok" ? `신호 기록: ${rk.signals.state === "error" ? "못 읽음" : "수집 전"}${rk.signals.reason_ko ? ` (${rk.signals.reason_ko})` : ""}`
        : "칸을 누르면 매매법 이름과 이번 주 숫자가 나와요"),
      rk.unknown_strategies && rk.unknown_strategies.length ? h("p", {class: "muted"}, `예전 설정의 매매법 ${fmt.int(rk.unknown_strategies.length)}개는 빼고 셌어요`) : null);
      return;
    }
    const pr = t.paper;
    put(tRead, h("p", null, h("b", {class: "lbh-trn"}, stratName(t.code)), h("span", {class: "muted"}, ` ${t.code}${t.type ? ` · ${t.type}` : ""} · ${t.tfs.map((x) => fmt.tfKo(x)).join("/")} · 설정 ${fmt.int(t.settings)}개 `),
      t.hold ? ui.pill("지금 포지션", "accent") : null),
    h("p", {class: "lbh-trk2"}, `이번 주 신호 ${t.n == null ? "못 읽음" : fmt.int(t.n)} · 오늘 ${t.today == null ? "—" : fmt.int(t.today)} · 진입 ${t.entered == null ? "—" : fmt.int(t.entered)}`,
      pr ? ` · 페이퍼(연습) ${fmt.int(pr.n)}번${pr.n ? ` ${fmt.int(pr.wins)}승 ${fmt.money(pr.pnl, true)} (모의)` : ""}` : "",
      t.last_ms ? ` · 마지막 ${t.last_ko || "신호"} ${ageKo(t.last_ms)}` : ""));
  }

  function tick() {
    const now = serverNow();
    const k = new Date(now + KST), two = (x) => String(x).padStart(2, "0");
    clockT.textContent = `${two(k.getUTCHours())}:${two(k.getUTCMinutes())}:${two(k.getUTCSeconds())}`;
    for (const el of root.querySelectorAll("[data-until]")) {
      const left = (Number(el.dataset.until) - now) / 1000;
      el.textContent = left > 0 ? clockOf(left) : "곧 다시 확인";
    }
    for (const el of root.querySelectorAll("[data-wuntil]")) {
      const left = (Number(el.dataset.wuntil) - now) / 1000, row = el.closest ? el.closest(".lbh-pwrow") : null;
      el.textContent = left > 0 ? clockOf(left) : "시간 지남 · 진입 없음";
      if (row) row.classList.toggle("gone", left <= 0);
    }
    for (const r of [...Object.values(R), ...MIXES.map((m) => m.r)]) if (r.asOf && (r.el.dataset.led === "run" || r.el.dataset.led === "stale")) r.ledSub.textContent = `${ageKo(r.asOf)} 기록`;
    if (now % 10000 < 1000) for (const el of fList.querySelectorAll("[data-t]")) el.textContent = ageKo(Number(el.dataset.t));
    tickDial();
  }

  // a real new entry (after the first look): particles from its strategy's arc to its coin
  function entryStreams(d) {
    const entries = (d.fills || []).filter((f) => f.kind === "entry");
    const pa = by(d.accts, "paper"), pp = pa && pa.state === "ok" ? pa.position : null;
    if (st.entrySeen) {
      for (const f of entries) {
        if (st.entrySeen.has(f.key) || serverNow() - f.t > RECENT_MS) continue;
        orb.stream(pp && pp.symbol === f.symbol ? pp.strategy_id : null, f.symbol, "entry");
      }
    }
    st.entrySeen = new Set(entries.map((f) => f.key));
  }

  function drawAll() {
    const d = st.d, ids = execIds(d);
    addReactors(ids);
    for (const id of ids) setReactor(R[id], d ? by(d.accts, id) : null, d ? by(d.execs, id) : null);
    setSoon();
    setMixes();
    for (const m of MIXES) if (shownMix(m) && !m.d && !m.busy && !m.err) loadMix(m).catch(() => {});
    drawBot();
    drawStatus();
    drawCenter();
    drawCkpt();
    drawDial();
    drawEntry();
    drawResult();
    drawFeed();
    drawTicker();
    if (!fNow.d) { drawWait(); drawLikely(); }
  }

  // ---- motion only while seen
  const still = () => { root.dataset.still = document.hidden ? "1" : ""; };
  still();
  ctx.listen(document, "visibilitychange", still);
  ctx.every(NOW_MS, () => fNow.load().catch(() => {}));
  ctx.every(CAL_MS, () => fCal.load().catch(() => {}));
  ctx.every(RANK_MS, () => fRank.load().catch(() => {}));
  ctx.every(MIX_MS, () => { for (const m of MIXES) loadMix(m).catch(() => {}); });
  ctx.every(1000, tick, {now: true});
  ctx.watch("ticker", () => {
    if (center.dataset.mode === "pos") { drawCenter(); drawEntry(); }
    for (const m of MIXES) { const mb = liveOf(m); if (mb && mb.position) setMix(m); }
  });
  ctx.watch("board", () => { if (fRank.d) drawTiles(); });
  drawAll();

  return {
    el: root,
    /** A new summary answer (d) or a failed refresh (d null, state "failed"): the last answer stays (livebots.js dims it). */
    set(d, state) {
      st.state = state;
      if (d) st.d = d;
      drawAll();
      if (d) { milestones(d); entryStreams(d); }
    },
    /** (livebots.js) a light turned red or an executor halted, really, since the last answer: its reactor lights once. */
    alarm(list) { for (const a of list || []) if (R[a.id]) motion.ring(R[a.id].el, "down"); },
  };
}

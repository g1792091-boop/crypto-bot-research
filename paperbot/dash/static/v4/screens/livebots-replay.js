// 실거래 › 다시보기 (#/livebots/replay?id=<paper trade id>; owners 10/19 "D2" 거래 다시보기): any closed trade of the live
// setup played back on its 1-minute bars: entry → the first stop → the ladder locks stepping up (lock 10 % net ROE when the
// best net ROE reaches 11 %, then the config's later steps; the server's rebuild and ladder_ko) → exit, with the executors
// that followed it. /api/v4/livebots/replay (the list)
// and /api/v4/livebots/replay/<id> (dash/more/livetape.py: the record, its bars, the stop path rebuilt minute by minute with
// the engine's own functions, the executors' paired trades). Other screens link here with replayHref(id).
//   고르기  the closed trades, newest first: coin, side, strategy · timeframe, net ROE, 이김 / 짐 chips of one size, the
//           executors' badges (B / M with their own result); the newest trade by default, the hash's id when there is one
//   무대    a canvas: the candles, the entry line, the stop line stepping up, the lock markers ("+11% 도달 → 10% 잠금"), the
//           exit, the executors' entry / exit ticks in their colours; ▶ 재생 / ❚❚ 멈춤, 1× 4× 16×, a scrubber (or a tap on
//           the chart); the readout (time, price, net ROE, the stop in force, the best net ROE so far), the events lighting
//           up as it plays; when the trade has closed, the result card (net ROE large, a loss as large as a win)
// 추세판단 봇 (owners 10/21): a trade entered before its start (the server's ``prev``) carries the 거래 tab's 전환 전 tag in
// the list and the head, and the result says it is the bot before it's (the position the new bot closed at its start:
// 전환 전 포지션 정리, SWITCH; its close is not rebuilt, the server says why).
// HONESTY: every number is the record's or the server's rebuild; no bars = 1분봉 없음 / 수집 전 / 못 읽음 (never a drawn
// candle the rule bot did not record); a rebuild that ends differently from the record = 기록과 다름 with both values, the
// record still shown as the result; paper money and real money each carry their caption; nothing here sends anything.
// Motion: it plays once and stops (nothing endless), a frame at most every 33 ms, only while the screen is shown; under
// prefers-reduced-motion nothing plays by itself (the end is shown at once) and nothing animates in; the scrubber works.
// The canvas sits pinned inside a box of fixed height (its size never feeds back into the layout), at the box's size x
// devicePixelRatio (2 at most, lowered above MAX_PX pixels).
import {h, put, ui, fmt, motion} from "../core/pb.js";
import {acctTag, sourceState} from "./livebots-kit.js";

export const API = "/api/v4/livebots/replay";
export const SPEEDS = [{id: "1", label: "1×", x: 1}, {id: "4", label: "4×", x: 4}, {id: "16", label: "16×", x: 16}];
const SPEED0 = "4";
const BAR_MS = 250;                      // at 1× one shown bar every 250 ms (4×: a 2-hour window in about 11 seconds)
const FRAME_MS = 33;
const MAX_PX = 1400000;                  // the canvas at most this many pixels (devicePixelRatio lowered above it)
const LIST_MS = 30 * 1000;
const ONE_MS = 30 * 1000;                // a trade whose answer is not final yet (bars after the exit, an executor closing)
const PAGE = 8;
const EXIT_KO = {SL: "손절", LOCK: "잠금 익절", LIQ: "강제청산", REV: "빠른 청산", JUDGE: "감독 청산(추세 뒤집힘)", TIME: "감독 청산(시간 정리)", SWITCH: "전환 전 포지션 정리",
  HALT: "멈춤 청산", MANUAL: "수동 청산", END: "끝냄"};
const STATE_KO = {matched: "따라감", missed: "안 따라감", before: "시작 전", open: "닫는 중", unknown: "모름"};
const TF_KO = {"5m": "5분봉", "1h": "1시간봉"};
const ENTRY_KO = {ref: "참고 가격 체결이라 진입 봉엔 잠금 안 함", open: "진입 봉 시가 체결이라 진입 봉부터 잠금 계산"};

// ---------------------------------------------------------------- pure functions (node tests: tests/test_dash_livebots_replay.py)
const num = (x) => (x == null || x === "" || typeof x === "boolean" || !Number.isFinite(Number(x)) ? null : Number(x));

/** The link other screens use: '#/livebots/replay?id=123' (no id: the newest trade). */
export function replayHref(tradeId) {
  const v = num(tradeId);
  return v == null ? "#/livebots/replay" : `#/livebots/replay?id=${Math.trunc(v)}`;
}
/** The trade id of a hash like '#/livebots/replay?id=123', else null. */
export function idFromHash(hash) {
  const q = String(hash || "").split("?")[1];
  if (!q) return null;
  const v = new URLSearchParams(q).get("id");
  return v && /^\d{1,12}$/.test(v) ? Number(v) : null;
}
/** A ratio as a percent without needless decimals: 0.11 -> '11%', 0.125 -> '12.5%'. */
export function pctNice(x) {
  const v = num(x);
  if (v == null) return "—";
  const p = v * 100;
  return fmt.pctOf(p, Math.abs(p - Math.round(p)) < 1e-6 ? 0 : 1);
}
/** A lock in the owners' words: '+11% 도달 → 10% 잠금' (the trigger of the lock that was set). */
export function lockLabel(k) {
  return `+${pctNice(k && k.trigger)} 도달 → ${pctNice(k && k.lock)} 잠금${k && k.steps > 1 ? ` (한 봉에 ${fmt.int(k.steps)}칸)` : ""}`;
}
/** Korea time with seconds: '10/19 16:09:59'. */
export function kstS(ms) {
  const v = num(ms);
  if (v == null) return "—";
  const sec = Math.floor((((v % 60000) + 60000) % 60000) / 1000);
  return `${fmt.kst(v)}:${String(sec).padStart(2, "0")}`;
}
const reasonKo = (r) => EXIT_KO[r] || String(r ?? "—");
/** 전환 전: a trade entered before the 추세판단 봇's start (the server's ``prev``), the bot before it's (the 거래 tab's tag). */
const prevPill = () => ui.pill("전환 전", "warn", "추세판단 봇이 켜지기 전에 들어간 거래예요 (예전 봇)");
/** What a trade from before the switch is, in one line (null for the bot's own): the position the new bot closed at its
 *  start (SWITCH) or another trade of the bot before it; never counted in the new bot's record. */
export function prevKo(t) {
  if (!t || !t.prev) return null;
  return t.exit_reason === "SWITCH" ? "예전 봇이 연 포지션을 새 봇(추세판단 봇)이 켜지며 바로 닫았어요 (전환 전 포지션 정리) · 새 봇 성적에 세지 않아요"
    : "새 봇(추세판단 봇)이 켜지기 전 예전 봇의 거래예요 · 새 봇 성적에 세지 않아요";
}

/** The value of a 기록과 다름 item in words (its kind: time / price / roe / reason / exit). */
export function itemVal(kind, v) {
  if (v == null) return kind === "exit" ? "이 창 안에서 끝나지 않음" : kind === "roe" ? "잠금 없음" : "—";
  if (kind === "time") return kstS(v);
  if (kind === "price") return fmt.price(v);
  if (kind === "roe") return pctNice(v);
  if (kind === "reason") return reasonKo(v);
  if (kind === "exit") return `${kstS(v.t)} · ${fmt.price(v.price)} · ${reasonKo(v.reason)}`;
  return String(v);
}

/** The trade's events in time order: the entry, the executors' entries, each lock, the exit, the executors' exits, and
 *  the rebuilt exit when it differs from the record. {t, kind, who, tone, ko, price}. */
export function eventsOf(d) {
  if (!d || !d.trade) return [];
  const t = d.trade, out = [];
  const add = (e) => { if (num(e.t) != null) out.push(e); };
  add({t: t.entry_time, kind: "entry", ord: 0, tone: "accent", price: t.entry_price,
    ko: `진입 ${fmt.price(t.entry_price)} · 첫 손절선 ${fmt.price(t.stop_initial)}`});
  for (const x of d.execs || []) {
    if (x.state !== "matched") continue;
    add({t: x.entry_ts, kind: "entry", who: x.id, ord: 1, tone: "", price: x.entry_price, ko: `${x.name_ko} 진입 ${fmt.price(x.entry_price)}`});
    add({t: x.exit_ts, kind: "exit", who: x.id, ord: 1, tone: fmt.tone(x.pnl), price: x.exit_ref,
      ko: `${x.name_ko} 청산 · ${fmt.money(x.pnl, true)} USDT${x.est ? "≈" : ""}`});
  }
  for (const k of d.locks || []) add({t: k.t, kind: "lock", ord: 0, tone: "up", price: k.price, at: k.at, ko: `${lockLabel(k)} · 잠금선 ${fmt.price(k.price)}`});
  const rec = (d.exit && d.exit.record) || {};
  const xt = rec.t ?? t.exit_time, xp = rec.price ?? t.exit_price;
  add({t: xt, kind: "exit", ord: 0, tone: resultOf(d).tone, price: xp, ko: `${rec.reason_ko || t.reason_ko || reasonKo(t.exit_reason)} ${fmt.price(xp)} · 순ROE ${fmt.pct(t.roe, 1)}`});
  const rb = d.exit && d.exit.rebuilt;
  if (rb && d.check && d.check.state === "differs" && (rb.t !== xt || rb.price !== xp)) {
    add({t: rb.t, kind: "rebuilt", ord: 2, tone: "warn", price: rb.price, ko: `다시 계산한 청산 ${reasonKo(rb.reason)} ${fmt.price(rb.price)} (기록과 다름)`});
  }
  const rank = {entry: 0, lock: 1, exit: 2, rebuilt: 3};
  return out.sort((a, b) => a.t - b.t || rank[a.kind] - rank[b.kind] || a.ord - b.ord);
}

/** Index of the last row whose time is at or before t (rows sorted by [0]); -1 before the first. */
function lastAt(rows, t) {
  let lo = 0, hi = rows.length - 1, out = -1;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (rows[m][0] <= t) { out = m; lo = m + 1; } else hi = m - 1;
  }
  return out;
}

/** The readout at time t: {phase: before / in / after, price (the shown bar's close), roe (net, as if closed at that
 *  close; after the exit the record's), stop in force, its lock, best net ROE so far}. */
export function frameAt(d, t) {
  const tr = d && d.trade;
  if (!tr) return {phase: "none"};
  const rows = (d.bars && d.bars.rows) || [], path = d.path || [];
  const i = lastAt(rows, t), bar = i >= 0 ? rows[i] : null;
  const phase = t < tr.entry_time ? "before" : t > tr.exit_time ? "after" : "in";
  const out = {phase, t, i, price: bar ? bar[4] : null, roe: null, stop: null, best: null, lock: null};
  if (phase === "in") {
    const k = bar ? lastAt(path, bar[0]) : -1;
    const r = k >= 0 && path[k][0] === bar[0] ? path[k] : null;
    if (r) { out.stop = r[1]; out.best = r[2]; out.roe = r[3]; out.lock = r[6]; } else out.stop = tr.stop_initial;
  } else if (phase === "after") {
    const last = path[path.length - 1];
    out.roe = tr.roe; out.stop = tr.stop_final; out.lock = tr.lock_roe; out.best = last ? last[2] : null;
  }
  return out;
}

/** The result card's words: {big (net ROE), tone, reason, hold, pnl}. A loss is said exactly like a win. */
export function resultOf(d) {
  const t = (d && d.trade) || {};
  const big = fmt.pct(t.roe, 1);
  return {big, tone: fmt.tone(t.roe, big) || (t.win ? "up" : "down"), reason: t.reason_ko || reasonKo(t.exit_reason),
    hold: num(t.hold_ms) == null ? "—" : fmt.dur(t.hold_ms / 1000), pnl: num(t.pnl) == null ? "—" : `${fmt.money(t.pnl, true)} USDT`};
}

/** The price range of the chart for the whole window (fixed while it plays): the bars, the entry, every stop, the exit and
 *  the executors' prices near the trade; 8 % padding. */
export function scaleOf(d) {
  const xs = [];
  for (const r of (d.bars && d.bars.rows) || []) xs.push(r[2], r[3]);
  const t = d.trade || {};
  for (const v of [t.entry_price, t.exit_price, t.stop_initial, t.stop_final]) if (num(v) != null) xs.push(Number(v));
  for (const s of d.stops || []) if (num(s[1]) != null) xs.push(Number(s[1]));
  const ref = num(t.entry_price);
  for (const x of d.execs || []) {
    for (const v of [x.entry_price, x.exit_ref]) if (num(v) != null && ref && Math.abs(v / ref - 1) < 0.05) xs.push(Number(v));
  }
  const ok = xs.filter((v) => num(v) != null);
  if (!ok.length) return null;
  let lo = Math.min(...ok), hi = Math.max(...ok);
  if (hi - lo < 1e-12) { lo -= Math.abs(lo) * 0.001 || 1; hi += Math.abs(hi) * 0.001 || 1; }
  const pad = (hi - lo) * 0.08;
  return {lo: lo - pad, hi: hi + pad};
}

const STEPS_T = [60e3, 5 * 60e3, 10 * 60e3, 15 * 60e3, 30 * 60e3, 3600e3, 2 * 3600e3, 3 * 3600e3, 6 * 3600e3, 12 * 3600e3, 86400e3];
/** Price ticks: about n round numbers between lo and hi. */
function priceTicks(lo, hi, n) {
  const raw = (hi - lo) / Math.max(1, n), p = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw) || 10 * p;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(v);
  return out;
}
/** Time ticks in Korea time: the first step that leaves at least ~90 px between two labels. */
function timeTicks(t0, t1, w) {
  const span = t1 - t0, step = STEPS_T.find((s) => span / s <= Math.max(2, w / 92)) || STEPS_T[STEPS_T.length - 1];
  const k = 9 * 3600e3, out = [];
  for (let v = Math.ceil((t0 + k) / step) * step - k; v <= t1; v += step) out.push(v);
  return out;
}

// ---------------------------------------------------------------- the view
/** replayView(ctx) -> {el, set()}: its own endpoints (the list every 30 s; a trade until its answer is final). */
export function replayView(ctx) {
  const reduced = () => motion.reduced();
  const st = {list: null, listAt: 0, sel: null, d: null, dKey: "", head: 0, playing: false, speed: SPEED0, raf: 0, last: 0,
    events: [], evEls: [], scale: null, busy: false, oneErr: null, open: false};
  // ---- the picker
  const pg = ui.pager({size: PAGE, row: (r) => rowEl(r), empty: () => (st.list ? ui.empty("아직 닫힌 거래가 없어요") : motion.shimmer(3))});
  const pickSum = h("span", {class: "lbrp-psum"});
  const tog = h("button", {type: "button", class: "lbrp-ptog", "aria-expanded": "false", onclick: () => setOpen(!st.open)}, "다른 거래 고르기");
  const pickState = h("div", {class: "lb-slot"});
  const pick = h("section", {class: "lbrp-pick", "aria-label": "거래 고르기", dataset: {open: "0"}},
    h("div", {class: "lbrp-phead"}, h("h2", null, "닫힌 거래"), pickSum, tog), pickState, h("div", {class: "lbrp-plist"}, pg.el));
  // ---- the stage
  const titleBox = h("div", {class: "lbrp-tline"}, motion.shimmer(1));
  const checkSlot = h("div", {class: "lbrp-checkw"});
  const stepNote = h("p", {class: "lbrp-step", hidden: true});
  const probe = h("span", {class: "lbrp-probe", "aria-hidden": "true"});
  const pin = {position: "absolute", left: "0", top: "0", width: "100%", height: "100%", display: "block"};
  const cv = h("canvas", {class: "lbrp-cv", role: "img", "aria-label": "거래 다시보기 차트", style: pin});
  const g = cv.getContext ? cv.getContext("2d") : null;
  const stateBox = h("div", {class: "lbrp-nobars", hidden: true});
  const box = h("div", {class: "lbrp-chartbox", style: {position: "relative", overflow: "hidden"}}, cv, probe, stateBox);
  const playBtn = h("button", {type: "button", class: "lbrp-play", "aria-pressed": "false", onclick: () => togglePlay()}, "▶ 재생");
  const speedSeg = ui.seg(SPEEDS.map((s) => ({id: s.id, label: s.label})), st.speed, (id) => { st.speed = id; }, {label: "재생 속도"});
  const scrub = h("input", {type: "range", class: "lbrp-scrub", min: "0", max: "0", step: "1", value: "0", "aria-label": "재생 위치"});
  const clock = h("span", {class: "lbrp-clock num"}, "—");
  const ctl = h("div", {class: "lbrp-ctl"}, playBtn, speedSeg, h("div", {class: "lbrp-scrubw"}, scrub, clock));
  const rc = (k) => { const v = h("b", {class: "num"}, "—"); return {el: h("div", {class: "lbrp-rc"}, h("span", {class: "k"}, k), v), v}; };
  const R = {t: rc("시각"), px: rc("가격"), roe: rc("순ROE"), stop: rc("손절선"), best: rc("최고 순ROE")};
  const readout = h("div", {class: "lbrp-read", role: "status", "aria-live": "off"}, Object.values(R).map((x) => x.el));
  const tl = h("ol", {class: "lbrp-tl", "aria-label": "이 거래에서 일어난 일"});
  const res = h("section", {class: "lbrp-res", "aria-label": "결과", hidden: true});
  const rules = h("div", {class: "lbrp-rules"});
  const foot = h("div", {class: "lbrp-foot"});
  const oneState = h("div", {class: "lb-slot"});
  const stageBody = h("div", {class: "lbrp-sbody"}, checkSlot, stepNote, box, ctl, readout,
    h("div", {class: "lbrp-low"}, h("div", {class: "lbrp-tlw"}, h("h3", null, "일어난 일"), tl), res), rules, foot);
  const stage = h("section", {class: "lbrp-stage", "aria-label": "거래 다시보기"},
    h("div", {class: "lbrp-head"}, h("h2", null, "거래 다시보기"), titleBox), oneState, stageBody);
  const listState = h("div", {class: "lb-slot"});
  const body = h("div", {class: "lbrp-grid"}, pick, stage);
  const el = h("div", {class: "lbrp stack"}, listState, body);

  function setOpen(v) {
    st.open = !!v;
    pick.dataset.open = st.open ? "1" : "0";
    tog.setAttribute("aria-expanded", String(st.open));
  }

  // ---- picker rows
  function execBadge(x) {
    const val = x.state === "matched" ? `${fmt.money(x.pnl, true)}${x.est ? "≈" : ""}` : STATE_KO[x.state] || x.state || "—";
    return h("span", {class: ["lbrp-xb", "lb-a-" + x.id, x.state === "matched" ? fmt.tone(x.pnl) : "off"],
      title: `${x.name_ko || x.id}: ${x.state === "matched" ? `따라감 · ${fmt.money(x.pnl, true)} USDT (실거래)` : x.why_ko || STATE_KO[x.state] || ""}`},
    h("i", {class: "lb-sw", "aria-hidden": "true"}), h("b", null, x.s || x.id), h("span", {class: "num"}, val));
  }
  function rowEl(r) {
    const on = st.sel != null && r.id === st.sel;
    const roe = fmt.pct(r.roe, 1);
    return h("button", {type: "button", role: "listitem", class: ["lbrp-row", on ? "on" : "", r.win ? "win" : "loss"], "aria-current": on ? "true" : null,
      onclick: () => choose(r.id, true)},
    h("span", {class: ["lbrp-wl", r.win ? "win" : "loss"]}, r.win ? "이김" : "짐"),
    h("span", {class: "lbrp-rmain"},
      h("span", {class: "lbrp-rcoin"}, h("b", null, fmt.coin(r.symbol)), ui.sideTag(r.side), h("span", {class: "lbrp-rlev"}, fmt.lev(r.leverage)),
        r.prev ? prevPill() : null),
      h("span", {class: "lbrp-rstrat"}, `${fmt.stratKo(r.strategy_id || "—")} · ${fmt.tfKo(r.timeframe)}`),
      h("span", {class: "lbrp-rtime"}, `${fmt.kst(r.exit_time)} · ${r.hold_ms == null ? "—" : fmt.dur(r.hold_ms / 1000)} · ${r.reason_ko || reasonKo(r.exit_reason)}`)),
    h("b", {class: ["num", "lbrp-rroe", fmt.tone(r.roe, roe)]}, roe),
    h("span", {class: "lbrp-xbs"}, (r.execs || []).map(execBadge)));
  }

  // ---- the stage: head, check, chart state, rules, timeline, result
  function drawHead(d) {
    const t = d.trade, r = resultOf(d), ko = fmt.stratKo(t.strategy_id || "—");
    put(titleBox,
      h("span", {class: ["lbrp-wl", t.win ? "win" : "loss"]}, t.win ? "이김" : "짐"),
      h("b", {class: "lbrp-tcoin"}, fmt.coin(t.symbol)), ui.sideTag(t.side), h("span", null, fmt.lev(t.leverage)),
      h("span", {class: "lbrp-tstrat"}, ko !== t.strategy_id && t.strategy_id ? `${ko} (${t.strategy_id})` : ko, ` · ${fmt.tfKo(t.timeframe)}`),
      h("span", {class: "lbrp-ttime"}, `${fmt.kst(t.entry_time)} → ${fmt.kst(t.exit_time)} · ${r.hold}`),
      t.prev ? prevPill() : null,
      h("span", {class: "lbrp-tid"}, `#${fmt.int(t.id)}`));
  }
  function drawCheck(d) {
    const c = d.check || {};
    if (c.state === "differs") {
      put(checkSlot, h("div", {class: "lbrp-differs", role: "status"},
        h("p", null, h("b", null, "기록과 다름"), " 1분봉으로 다시 계산한 길이 봇의 기록과 달라요. 결과는 기록 그대로 보여 드려요"),
        h("ul", null, (c.items || []).map((it) => h("li", null, h("b", null, it.ko), ` 기록 ${itemVal(it.kind, it.record)} · 다시 계산 ${itemVal(it.kind, it.rebuilt)}`))),
        c.why_ko ? h("p", {class: "note"}, c.why_ko) : null));
    } else if (c.state === "same") {
      put(checkSlot, h("p", {class: "lbrp-check same", title: "봇 엔진의 계산 순서(손절 확인 뒤 잠금 올림)를 이 거래의 1분봉으로 다시 해 본 결과"},
        h("b", null, "기록과 같음"), " · 1분봉으로 다시 계산한 손절·잠금·청산이 봇의 기록과 같아요", c.why_ko ? ` · ${c.why_ko}` : ""));
    } else {
      put(checkSlot, h("p", {class: "lbrp-check none"}, h("b", null, "다시 계산 못 함"), ` · ${c.why_ko || "1분봉이 없어요"}`));
    }
  }
  function drawBarsState(d) {
    const b = d.bars || {};
    const ok = b.state === "ok" && (b.rows || []).length > 0;
    stateBox.hidden = ok;
    cv.hidden = !ok;
    ctl.hidden = !ok;                                   // nothing to play without bars: the record below says it all
    stepNote.hidden = !(ok && b.step_ko);
    stepNote.textContent = ok && b.step_ko ? `${b.step_ko}${b.partial ? ` · 분이 빠진 ${TF_KO[b.tf] || b.tf} ${fmt.int(b.partial)}개는 있는 분으로만 만든 봉` : ""}` : "";
    if (ok) { put(stateBox); return; }
    const head = b.state === "none" ? ui.pill("1분봉 없음", "warn") : b.state === "missing" ? ui.notYet("수집 전", b.reason_ko) : ui.pill("못 읽음", "bad");
    put(stateBox, h("div", {class: "lbrp-nbin"}, head, h("p", null, b.reason_ko || "1분봉을 읽지 못했어요"),
      b.reason && b.state === "error" ? h("p", {class: "lbrp-raw"}, b.reason) : null,
      h("p", {class: "note"}, "차트 없이 기록만 보여 드려요 (지어낸 봉은 그리지 않아요)")));
  }
  function drawRules(d) {
    const r = d.rules || {}, b = d.bars || {};
    const parts = [r.ladder_ko ? `계단 익절: ${r.ladder_ko}` : "계단 익절 숫자 기록 없음",
      num(r.round_trip) != null ? `왕복 비용 ${fmt.pct(r.round_trip, 2, false)} (수수료 ${fmt.pct(r.taker_fee, 3, false)} + 미끄러짐 ${fmt.pct(r.slippage, 2, false)}, 양쪽)` : null,
      ENTRY_KO[r.entry_bar] || null, b.step_ko || null,
      b.state === "ok" && b.tf === "1m" ? "1분봉 = 봇이 실제로 걸어간 규칙봇 기록" : null].filter(Boolean);
    put(rules, h("p", null, parts.join(" · ")),
      (d.notes_ko || []).map((n) => h("p", {class: "note"}, n)));
    put(foot, ui.assumeLine(["closed"], "페이퍼(연습) · 결과는 거래 기록 그대로"),
      ui.assumeLive("실행기 손익 · ≈ = 체결 기록 전 지갑 변화로 어림 · 청산 기준가 = 실행기가 닫기 직전에 읽은 가격(체결가 아님)"));
  }
  function drawTimeline(d) {
    st.events = eventsOf(d);
    st.evEls = st.events.map((e) => h("li", {class: ["lbrp-ev", e.kind, e.tone || ""], dataset: {who: e.who || "paper"}},
      h("span", {class: "lbrp-evt num"}, fmt.hm(e.t)), h("i", {class: "lbrp-evd", "aria-hidden": "true"}),
      e.who ? acctTag(e.who, {short: true}) : acctTag("paper", {short: true}), h("span", {class: "lbrp-evk"}, e.ko)));
    put(tl, st.evEls);
  }
  function drawResult(d) {
    const r = resultOf(d), t = d.trade;
    const xs = (d.execs || []).map((x) => h("div", {class: ["lbrp-rx", x.state]}, acctTag(x.id),
      x.state === "matched"
        ? h("span", null, h("b", {class: ["num", fmt.tone(x.pnl)]}, `${fmt.money(x.pnl, true)} USDT${x.est ? "≈" : ""}`),
          ` · ROE ${fmt.pct(x.roe, 1)} · ${x.reason_ko || reasonKo(x.reason)}`,
          x.stop_final != null ? ` · 거래소 ${x.locked ? "잠금선" : "손절선"} ${fmt.price(x.stop_final)}` : "",
          x.entry_price != null ? ` · 진입 ${fmt.price(x.entry_price)}${x.slip_vs_paper != null ? ` (페이퍼보다 ${fmt.pct(x.slip_vs_paper, 3)})` : ""}` : "")
        : h("span", {class: "muted"}, `${STATE_KO[x.state] || x.state}${x.why_ko ? ` · ${x.why_ko}` : x.reason_ko ? ` · ${x.reason_ko}` : ""}`)));
    put(res,
      h("div", {class: "lbrp-reshead"}, h("span", {class: "lbrp-resk"}, "결과 · 순ROE"), h("span", {class: ["lbrp-wl", t.win ? "win" : "loss"]}, t.win ? "이김" : "짐")),
      h("b", {class: ["lbrp-big", "num", r.tone]}, r.big),
      h("p", {class: "lbrp-resl"}, acctTag("paper"), " ", h("b", null, r.reason), ` · ${r.hold} 보유 · `, h("span", {class: ["num", r.tone]}, r.pnl),
        t.lock_roe != null ? ` · 마지막 잠금 ${pctNice(t.lock_roe)}` : " · 잠금 없음"),
      prevKo(t) ? h("p", {class: "lbrp-prev"}, prevPill(), ` ${prevKo(t)}`) : null,
      h("div", {class: "lbrp-resx"}, h("span", {class: "lbrp-resk"}, "실거래 실행기"), xs.length ? xs : h("span", {class: "muted"}, "실행기 기록 없음")));
  }

  // ---- the play head
  const win = () => (st.d && st.d.bars && st.d.bars.state === "ok" && (st.d.bars.rows || []).length ? st.d.bars : null);
  function setHead(t, user) {
    const b = win();
    if (!st.d) return;
    if (b) st.head = Math.max(b.from_ms, Math.min(b.to_ms, t)); else st.head = st.d.trade.exit_time + 1;
    const f = frameAt(st.d, st.head), tr = st.d.trade;
    if (b) {
      scrub.value = String(Math.max(0, f.i));
      clock.textContent = `${fmt.hm(st.head)}`;
    }
    R.t.v.textContent = b ? fmt.kst(st.head) : fmt.kst(tr.exit_time);
    R.px.v.textContent = f.price == null ? (b ? "—" : fmt.price(tr.exit_price)) : fmt.price(f.price);
    const roeTxt = f.phase === "before" ? "진입 전" : f.roe == null ? "—" : fmt.pct(f.roe, 1);
    R.roe.v.textContent = roeTxt;
    R.roe.v.className = ["num", f.roe == null ? "" : fmt.tone(f.roe, roeTxt)].join(" ");
    R.roe.el.firstChild.textContent = f.phase === "after" ? "결과 순ROE" : "순ROE";
    R.stop.el.firstChild.textContent = f.lock != null ? `잠금선 ${pctNice(f.lock)}` : "손절선";
    R.stop.v.textContent = f.phase === "before" ? "—" : f.stop == null ? "—" : fmt.price(f.stop);
    R.stop.v.className = ["num", f.lock != null ? "up" : f.stop != null && f.phase !== "before" ? "down" : ""].join(" ");
    R.best.v.textContent = f.best == null ? "—" : fmt.pct(f.best, 1);
    let nowIdx = -1;
    st.events.forEach((e, i) => { const on = e.t <= st.head; st.evEls[i].classList.toggle("on", on); if (on) nowIdx = i; });
    st.evEls.forEach((x, i) => x.classList.toggle("now", i === nowIdx));
    const done = st.head >= tr.exit_time;
    if (done && res.hidden) { res.hidden = false; if (!user && !reduced()) motion.fadeIn(res); }
    else if (!done) res.hidden = true;
    playBtn.textContent = st.playing ? "❚❚ 멈춤" : b && st.head >= b.to_ms ? "↺ 다시 재생" : "▶ 재생";
    playBtn.setAttribute("aria-pressed", String(st.playing));
    playBtn.disabled = !b;
    scrub.disabled = !b;
    draw();
  }
  function stop() {
    st.playing = false;
    if (st.raf) cancelAnimationFrame(st.raf);
    st.raf = 0;
  }
  function frame(now) {
    st.raf = 0;
    const b = win();
    if (!st.playing || !ctx.alive() || !b || !cv.isConnected) { if (st.playing && !cv.isConnected) stop(); return; }
    if (st.last && now - st.last < FRAME_MS) { st.raf = requestAnimationFrame(frame); return; }
    const dt = st.last ? Math.min(200, now - st.last) : 0;
    st.last = now;
    const x = (SPEEDS.find((s) => s.id === st.speed) || SPEEDS[1]).x;
    const t = st.head + dt * x * b.tf_ms / BAR_MS;
    if (t >= b.to_ms) { st.playing = false; setHead(b.to_ms, false); return; }
    setHead(t, false);
    st.raf = requestAnimationFrame(frame);
  }
  function play(from) {
    const b = win();
    if (!b) return;
    if (from != null) st.head = from;
    st.playing = true;
    st.last = 0;
    setHead(st.head, false);
    if (!st.raf) st.raf = requestAnimationFrame(frame);
  }
  function togglePlay() {
    const b = win();
    if (!b) return;
    if (st.playing) { stop(); setHead(st.head, true); return; }
    play(st.head >= b.to_ms ? b.from_ms : null);
  }
  scrub.addEventListener("input", () => {
    const b = win();
    if (!b) return;
    stop();
    const r = b.rows[Math.max(0, Math.min(b.rows.length - 1, Number(scrub.value) || 0))];
    setHead(r[0] + b.tf_ms - 1, true);
  });

  // ---- the canvas (colours from the skin's tokens through a hidden probe: never a literal colour)
  const o = {w: 0, h: 0, dpr: 1, col: null, font: null, ff: null};
  function tokens() {
    const read = (v) => { probe.style.color = `var(${v})`; const c = getComputedStyle(probe).color; return c || null; };
    const cs = getComputedStyle(document.documentElement);
    o.col = {up: read("--up"), down: read("--down"), ink: read("--ink"), ink2: read("--ink-2"), muted: read("--muted"), line: read("--line"),
      accent: read("--accent"), warn: read("--warn"), paper: read("--series-coin"), bybit: read("--series-core"), mexc: read("--series-m5"),
      shade: read("--accent-soft"), bg: read("--console")};
    o.fs = parseFloat(String(cs.getPropertyValue("--t-2xs") || "").trim()) || 12;
    o.ff = String(cs.getPropertyValue("--f-term") || "").trim() || "monospace";
  }
  function layout() {
    const r = box.getBoundingClientRect ? box.getBoundingClientRect() : {width: 0, height: 0};
    if (!r.width || !r.height) return false;
    let dpr = Math.min(2, (typeof window !== "undefined" && window.devicePixelRatio) || 1);
    if (r.width * r.height * dpr * dpr > MAX_PX) dpr = Math.max(1, Math.sqrt(MAX_PX / Math.max(1, r.width * r.height)));
    const w = Math.round(Math.min(r.width, 2400)), hh = Math.round(Math.min(r.height, 1200));
    if (w === o.w && hh === o.h && dpr === o.dpr) return false;
    o.w = w; o.h = hh; o.dpr = dpr;
    cv.width = Math.max(1, Math.round(w * dpr)); cv.height = Math.max(1, Math.round(hh * dpr));
    return true;
  }
  function draw() {
    const d = st.d, b = win();
    if (!g || !d || !b || !o.w || !o.col || !st.scale) return;
    const c = o.col, tr = d.trade, side = Number(tr.side) > 0 ? 1 : -1, rows = b.rows;
    g.setTransform(o.dpr, 0, 0, o.dpr, 0, 0);
    g.clearRect(0, 0, o.w, o.h);
    const t0 = b.from_ms, t1 = b.to_ms, lo = st.scale.lo, hi = st.scale.hi;
    const font = (wgt, k = 1) => `${wgt} ${Math.round(o.fs * k)}px ${o.ff}`;
    g.font = font(400);
    // the price column is as wide as its widest label (a phone never cuts '60,200.0')
    const padR = Math.ceil(Math.max(g.measureText(fmt.price(hi)).width, g.measureText(fmt.price(lo)).width) + 14);
    const x0 = 6, x1 = o.w - padR, y0 = 14, y1 = o.h - 22;
    o.x0 = x0; o.x1 = x1;
    const X = (t) => x0 + ((t - t0) / (t1 - t0)) * (x1 - x0);
    const Y = (p) => y1 - ((p - lo) / (hi - lo)) * (y1 - y0);
    const head = st.head;
    const labels = [];                     // the tags drawn last, stacked so that none covers another
    // grid and the price axis
    g.textBaseline = "middle";
    for (const v of priceTicks(lo, hi, Math.max(3, Math.round((y1 - y0) / 64)))) {
      const y = Math.round(Y(v)) + 0.5;
      g.strokeStyle = c.line; g.globalAlpha = 0.7; g.lineWidth = 1;
      g.beginPath(); g.moveTo(x0, y); g.lineTo(x1, y); g.stroke();
      g.globalAlpha = 1; g.fillStyle = c.muted; g.textAlign = "left";
      g.fillText(fmt.price(v), x1 + 6, y);
    }
    g.textBaseline = "alphabetic"; g.textAlign = "center";
    for (const v of timeTicks(t0, t1, x1 - x0)) {
      const x = Math.round(X(v)) + 0.5, half = g.measureText(fmt.hm(v)).width / 2;
      g.strokeStyle = c.line; g.globalAlpha = 0.45;
      g.beginPath(); g.moveTo(x, y0); g.lineTo(x, y1); g.stroke();
      g.globalAlpha = 1; g.fillStyle = c.muted;
      if (x - half >= 0 && x + half <= x1) g.fillText(fmt.hm(v), x, o.h - 6);     // a label the edge would cut is left out
    }
    // the trade's span
    const xe = X(tr.entry_time), xx = X(tr.exit_time);
    g.fillStyle = c.shade || c.accent; g.globalAlpha = c.shade ? 0.6 : 0.06;
    g.fillRect(xe, y0, Math.max(1, Math.min(xx, X(Math.max(head, tr.entry_time))) - xe), y1 - y0);
    g.globalAlpha = 1;
    // candles: shown up to the play head, a faint ghost after it (the scale never jumps)
    const bw = Math.max(1, ((x1 - x0) / Math.max(1, (t1 - t0) / b.tf_ms)) * 0.68);
    for (const r of rows) {
      const past = r[0] <= head;
      const up = r[4] >= r[1];
      const xc = X(r[0] + b.tf_ms / 2);
      g.globalAlpha = past ? 1 : 0.12;
      g.strokeStyle = g.fillStyle = up ? c.up : c.down;
      g.lineWidth = 1;
      g.beginPath(); g.moveTo(Math.round(xc) + 0.5, Y(r[2])); g.lineTo(Math.round(xc) + 0.5, Y(r[3])); g.stroke();
      const yo = Y(r[1]), yc = Y(r[4]);
      g.fillRect(xc - bw / 2, Math.min(yo, yc), bw, Math.max(1, Math.abs(yc - yo)));
    }
    g.globalAlpha = 1;
    // the entry line (from the entry)
    if (head >= tr.entry_time) {
      const y = Y(tr.entry_price);
      g.setLineDash([5, 4]); g.strokeStyle = c.accent; g.lineWidth = 1.2; g.globalAlpha = 0.85;
      g.beginPath(); g.moveTo(xe, y); g.lineTo(x1, y); g.stroke();
      g.setLineDash([]); g.globalAlpha = 1;
      g.fillStyle = c.accent;
      g.beginPath(); g.arc(xe, y, 4, 0, Math.PI * 2); g.fill();
      labels.push({text: `진입 ${fmt.price(tr.entry_price)}`, x: x1, y, colr: c.accent, axis: true});
    }
    // the stop line, stepping up (the server's change points; up to the play head and the end of the rebuilt path)
    const rb = d.exit && d.exit.rebuilt;
    const stopEnd = Math.min(head, rb ? rb.t : tr.exit_time);
    const stops = d.stops || [];
    let curStop = null, curLock = null;
    g.lineWidth = 2;
    for (let i = 0; i < stops.length; i++) {
      const [ts, p, lk] = stops[i];
      if (num(p) == null || ts > stopEnd) break;
      const te = Math.min(stopEnd, i + 1 < stops.length ? stops[i + 1][0] : stopEnd);
      const profit = (p - tr.entry_price) * side > 0;
      g.strokeStyle = profit ? c.up : c.down;
      if (!reduced()) { g.shadowColor = g.strokeStyle; g.shadowBlur = 6; }
      g.beginPath(); g.moveTo(X(ts), Y(p)); g.lineTo(X(te), Y(p)); g.stroke();
      if (i > 0 && num(stops[i - 1][1]) != null) { g.beginPath(); g.moveTo(X(ts), Y(stops[i - 1][1])); g.lineTo(X(ts), Y(p)); g.stroke(); }
      g.shadowBlur = 0;
      curStop = p; curLock = lk;
    }
    if (curStop != null && head <= (rb ? rb.t : tr.exit_time) && head >= tr.entry_time) {
      labels.push({text: curLock != null ? `잠금 ${pctNice(curLock)} ${fmt.price(curStop)}` : `손절 ${fmt.price(curStop)}`, x: x1, y: Y(curStop),
        colr: (curStop - tr.entry_price) * side > 0 ? c.up : c.down, axis: true});
    }
    // the lock markers ('+11% → 10% 잠금' at the price where the stop stepped)
    for (const k of d.locks || []) {
      if (k.t > head) continue;
      const x = X(k.at), y = Y(k.price);
      g.fillStyle = c.up;
      if (!reduced()) { g.shadowColor = c.up; g.shadowBlur = 10; }
      g.beginPath(); g.moveTo(x, y - 6); g.lineTo(x + 6, y); g.lineTo(x, y + 6); g.lineTo(x - 6, y); g.closePath(); g.fill();
      g.shadowBlur = 0;
      labels.push({text: `+${pctNice(k.trigger)} → ${pctNice(k.lock)} 잠금`, x: x + 9, y, colr: c.up, side, mx: x, my: y});
    }
    // the executors' entries (▲ / ▼) and exits (■), in their colours
    for (const x of d.execs || []) {
      if (x.state !== "matched") continue;
      const colr = c[x.id] || c.ink2;
      if (num(x.entry_ts) != null && x.entry_ts <= head && num(x.entry_price) != null) mark(X(x.entry_ts), Y(x.entry_price), side > 0 ? "up" : "down", colr);
      if (num(x.exit_ts) != null && x.exit_ts <= head && num(x.exit_ref) != null) mark(X(x.exit_ts), Y(x.exit_ref), "sq", colr);
    }
    // the exit (the record), and the rebuilt exit when it differs
    if (head >= tr.exit_time && num(tr.exit_price) != null) {
      const r = resultOf(d), colr = r.tone === "up" ? c.up : c.down, x = X(tr.exit_time), y = Y(tr.exit_price);
      g.fillStyle = colr;
      if (!reduced()) { g.shadowColor = colr; g.shadowBlur = 12; }
      g.beginPath(); g.arc(x, y, 6, 0, Math.PI * 2); g.fill();
      g.shadowBlur = 0;
      labels.push({text: `${r.reason} ${r.big}`, x: x + 10, y, colr, bold: true, side: -side, mx: x, my: y});
    }
    if (rb && d.check && d.check.state === "differs" && rb.t <= head && (rb.t !== tr.exit_time || rb.price !== tr.exit_price)) {
      g.strokeStyle = c.warn; g.lineWidth = 2; g.setLineDash([3, 3]);
      g.beginPath(); g.arc(X(rb.t), Y(rb.price), 8, 0, Math.PI * 2); g.stroke();
      g.setLineDash([]);
      labels.push({text: "다시 계산한 청산", x: X(rb.t) + 11, y: Y(rb.price), colr: c.warn, side, mx: X(rb.t), my: Y(rb.price)});
    }
    // the play head
    const f = frameAt(d, head);
    const xh = X(head);
    g.strokeStyle = c.accent; g.globalAlpha = 0.75; g.lineWidth = 1;
    g.beginPath(); g.moveTo(Math.round(xh) + 0.5, y0); g.lineTo(Math.round(xh) + 0.5, y1); g.stroke();
    g.globalAlpha = 1;
    if (f.price != null) {
      g.fillStyle = c.accent;
      if (!reduced()) { g.shadowColor = c.accent; g.shadowBlur = 12; }
      g.beginPath(); g.arc(xh, Y(f.price), 4, 0, Math.PI * 2); g.fill();
      g.shadowBlur = 0;
    }
    placeTags(labels, {x0, x1, y0, y1}, c);
  }
  /** The chart's tags (the axis tags first, then the markers' in time order): each moved up or down past the ones already
   *  placed, a marker's tag flipped to the marker's left when it would run into the price column. */
  function placeTags(labels, area, c) {
    const hh = Math.round(o.fs) + 8, put0 = [];
    const hit = (r) => put0.some((q) => r.x < q.x + q.w && q.x < r.x + r.w && r.y < q.y + q.h && q.y < r.y + r.h);
    const ordered = [...labels.filter((l) => l.axis), ...labels.filter((l) => !l.axis)];
    for (const l of ordered) {
      g.font = `${l.bold ? 800 : 700} ${Math.round(o.fs)}px ${o.ff}`;
      const w = Math.ceil(g.measureText(l.text).width + 10);
      let x = l.axis ? l.x + 1 : l.x;
      if (!l.axis && x + w > area.x1 - 2) x = Math.max(1, l.x - w - 18);   // flipped, never past the left edge (a long word: 전환 전 포지션 정리)
      const dir = l.side && l.side < 0 ? -1 : 1;
      let r = null;
      for (let k = 0; k < 9; k++) {
        const off = k === 0 ? 0 : (k % 2 ? dir : -dir) * Math.ceil(k / 2) * (hh + 2);
        const y = Math.max(area.y0 - 10, Math.min(area.y1 - hh + 10, l.y - hh / 2 + off));
        const cand = {x, y, w: l.axis ? Math.min(w, o.w - x - 1) : w, h: hh};
        if (!hit(cand) || k === 8) { r = cand; break; }
      }
      put0.push(r);
      if (l.mx != null && Math.abs(r.y + r.h / 2 - l.y) > 2) {           // moved away from its marker: a thin line back to it
        const ex = l.mx < r.x ? r.x : r.x + r.w, ey = Math.max(r.y, Math.min(r.y + r.h, l.my));
        g.strokeStyle = l.colr; g.globalAlpha = 0.6; g.lineWidth = 1;
        g.beginPath(); g.moveTo(l.mx, l.my); g.lineTo(ex, ey); g.stroke();
        g.globalAlpha = 1;
      }
      g.fillStyle = c.bg || c.line; g.globalAlpha = 0.9;
      g.fillRect(r.x, r.y, r.w, r.h);
      g.globalAlpha = 1; g.strokeStyle = l.colr; g.lineWidth = 1;
      g.strokeRect(r.x + 0.5, r.y + 0.5, r.w - 1, r.h - 1);
      g.fillStyle = l.colr; g.textAlign = "left"; g.textBaseline = "middle";
      g.fillText(l.text, r.x + 5, r.y + r.h / 2, r.w - 8);
      g.textBaseline = "alphabetic";
    }
  }
  function mark(x, y, kind, colr) {
    g.fillStyle = colr; g.strokeStyle = colr;
    g.beginPath();
    if (kind === "sq") g.rect(x - 4, y - 4, 8, 8);
    else if (kind === "up") { g.moveTo(x, y - 6); g.lineTo(x + 5, y + 4); g.lineTo(x - 5, y + 4); g.closePath(); }
    else { g.moveTo(x, y + 6); g.lineTo(x + 5, y - 4); g.lineTo(x - 5, y - 4); g.closePath(); }
    g.fill();
  }
  // a tap or a drag on the chart moves the play head there (and pauses)
  let dragging = false;
  const seek = (e) => {
    const b = win();
    if (!b || !o.w) return;
    const r = cv.getBoundingClientRect(), x0 = o.x0 || 6, x1 = o.x1 || o.w;
    const fr = Math.max(0, Math.min(1, (e.clientX - r.left - x0) / Math.max(1, x1 - x0)));
    stop();
    setHead(b.from_ms + fr * (b.to_ms - b.from_ms), true);
  };
  cv.addEventListener("pointerdown", (e) => { dragging = true; seek(e); });
  cv.addEventListener("pointermove", (e) => { if (dragging) seek(e); });
  for (const ev of ["pointerup", "pointercancel", "pointerleave"]) cv.addEventListener(ev, () => { dragging = false; });
  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => { if (layout()) draw(); });      // the box's size is fixed by its css, never by the canvas
    ro.observe(box);
    ctx.track(() => ro.disconnect());
  }
  ctx.track(() => stop());
  ctx.listen(document, "visibilitychange", () => { if (!document.hidden) { tokens(); layout(); draw(); } });

  // ---- data
  function showTrade(d, fresh) {
    st.d = d;
    st.scale = scaleOf(d);
    drawHead(d); drawCheck(d); drawBarsState(d); drawRules(d); drawTimeline(d); drawResult(d);
    const b = win();
    scrub.max = String(b ? Math.max(0, b.rows.length - 1) : 0);
    if (!fresh) { setHead(st.head, true); return; }
    stop();
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => { tokens(); layout(); draw(); });
    if (b && !reduced()) play(b.from_ms);
    else setHead(b ? b.to_ms : d.trade.exit_time + 1, true);
  }
  async function loadOne(id, fresh) {
    if (id == null) return;
    let d;
    try { d = await ctx.api(`/api/v4/livebots/replay/${id}`); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError") || st.sel !== id) return;
      if (e && e.status === 404) {
        put(oneState, h("div", {class: "lb-state bad"}, ui.pill("없음", "bad"), h("span", null, ` 이 번호의 거래가 없어요 (#${fmt.int(id)}). 목록에서 골라 주세요`)));
        stageBody.hidden = true; put(titleBox); return;
      }
      put(oneState, st.d && st.d.id === id ? ui.staleNote(e, 0, () => loadOne(id, false)) : ui.errorBox(e, () => loadOne(id, true)));
      if (!st.d || st.d.id !== id) { stageBody.hidden = true; put(titleBox); }
      throw e;
    }
    if (!ctx.alive() || st.sel !== id) return;
    put(oneState);
    if (d.state && d.state !== "ok") {
      stageBody.hidden = true; put(titleBox);
      put(oneState, sourceState(d, "페이퍼 DB"));
      return;
    }
    stageBody.hidden = false;
    const key = JSON.stringify({...d, now_ms: 0});
    if (!fresh && key === st.dKey) return;
    st.dKey = key;
    showTrade(d, fresh || !st.d || st.d.id !== d.id);
  }
  function choose(id, user) {
    if (id == null) return;
    const changed = st.sel !== id;
    st.sel = id;
    if (user) {
      try { window.history.replaceState(null, "", replayHref(id)); } catch (e) { /* keep the hash */ }
      setOpen(false);
    }
    pg.rerender();
    if (changed) {
      stop();
      put(oneState);
      if (!st.d || st.d.id !== id) { put(titleBox, motion.shimmer(1)); }
      loadOne(id, true).catch(() => {});
    }
  }
  async function loadList() {
    let d;
    try { d = await ctx.api(API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(listState, st.list ? ui.staleNote(e, st.listAt, () => loadList()) : ui.errorBox(e, () => loadList()));
      if (!st.list) body.hidden = true;
      throw e;
    }
    if (!ctx.alive()) return;
    st.list = d; st.listAt = Date.now();
    put(listState);
    body.hidden = false;
    if (d.state !== "ok") {
      put(pickState, sourceState(d, "페이퍼 DB"));
      pg.set([]);
      pickSum.textContent = "";
      if (st.sel == null) { stageBody.hidden = true; put(titleBox); }
      return;
    }
    put(pickState);
    const rows = d.rows || [];
    const w = rows.filter((r) => r.win).length;
    pickSum.textContent = rows.length ? `${fmt.int(d.n)}번 · 최근 ${fmt.int(rows.length)}번 중 ${fmt.int(w)}승 ${fmt.int(rows.length - w)}패` : "";
    tog.textContent = `다른 거래 고르기 (${fmt.int(d.n || 0)})`;
    pg.set(rows, true);
    if (st.sel == null) {
      if (!rows.length) { stageBody.hidden = true; put(titleBox, h("span", {class: "muted"}, "아직 닫힌 거래가 없어요")); return; }
      choose(d.newest_id ?? rows[0].id, false);
    }
  }

  // ---- start: the hash's trade (or the newest), the list beside it
  stageBody.hidden = true;
  const hashId = idFromHash(typeof location !== "undefined" ? location.hash : "") ?? idFromHash(`?id=${(ctx.params && ctx.params.query && ctx.params.query.id) || ""}`);
  loadList().catch(() => {}).then(() => { if (hashId != null && st.sel == null) choose(hashId, false); });
  if (hashId != null) { st.sel = hashId; put(titleBox, motion.shimmer(1)); loadOne(hashId, true).catch(() => {}); }
  ctx.every(LIST_MS, () => loadList().catch(() => {}), {now: false});
  ctx.every(ONE_MS, () => { if (st.d && st.d.final === false && st.sel === st.d.id) loadOne(st.sel, false).catch(() => {}); }, {now: false});
  return {el, set() {}};
}

// 터미널 kit (후보 리그): the panel frame, the ratio bar, the short ages, the failed-load note and the realized-P&L math
// every part of the 터미널 uses. Copied and adapted from the rule bot's v4 screens/terminal-kit.js, terminal-state.js and
// terminal-pnl-calc.js (paperbot/dash/static/v4; nothing is imported from there). Every string reaches the page as a
// text node (dom.js h()). The math at the bottom has no DOM (tests/test_candleague_term_ui.py runs it under node).
// D11: a DeepSeek account whose money the server hides (/api/positions "hidden", ds_money off) is counted only:
// hiddenPos / hiddenFill say so, and every part shows its side, coin and time, never a price, a size, a leverage or money.
import {h} from "../dom.js";
import * as fmt from "../fmt.js";
import {serverNow} from "../live.js";
import {reduced, visible} from "../v4kit.js";
import * as LK from "../lk.js";
import {ROLE_SHORT, tfKo, sideKo} from "../labels.js";

export const H = 3600000;
export const D = 24 * H;
export const KST = 9 * H;
/** The chart's timeframes (the engine trades 15분 · 30분 · 1시간 · 4시간; 1분 · 5분 are for looking closer). */
export const TFS = ["1m", "5m", "15m", "30m", "1h", "4h"];
export const TF_MS = {"1m": 60e3, "5m": 300e3, "15m": 900e3, "30m": 1800e3, "1h": 3600e3, "4h": 14400e3};
export const TF_SHORT = {"1m": "1분", "5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"};

// ---------------------------------------------------------------- numbers as the rule bot's terminal prints them
/** USDT amount with its sign: 1234.5 -> "+1,234.50" (null -> "—"). */
export const usdt = (v, sign = true) => (fmt.bad(v) ? "—" : fmt.num(v, 2, sign));
/** A ratio as a signed percent: 0.0312 -> "+3.1%". */
export const pctOf = (r, dec = 1, sign = true) => (fmt.bad(r) ? "—" : fmt.pct(Number(r) * 100, sign, dec));
/** A big USDT amount in Korean units: 12.0억, 3,400만, 950 (the rule bot's usdKo). */
export function usdKo(x) {
  if (fmt.bad(x)) return "—";
  const v = Number(x), a = Math.abs(v);
  return a >= 1e8 ? `${fmt.num(v / 1e8, 1)}억` : a >= 1e4 ? `${fmt.num(v / 1e4, 0)}만` : fmt.num(v, 0);
}
/** 1,234.5 -> "1.2K", 356 -> "356", -7,512 -> "−7.5K" (calendar cells, axis labels). */
export function short(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  const a = Math.abs(v);
  return a >= 1e6 ? `${fmt.num(v / 1e6, 1)}M` : a >= 1e4 ? `${fmt.num(v / 1e3, 0)}K` : a >= 1e3 ? `${fmt.num(v / 1e3, 1)}K` : fmt.num(v, 0);
}
const two = (x) => String(x).padStart(2, "0");
/** ms -> "mm:ss" or "h:mm:ss" (a countdown). */
export function mmss(ms) {
  const t = Math.max(0, Math.floor(Number(ms) / 1000));
  if (!Number.isFinite(t)) return "—";
  return `${t >= 3600 ? `${Math.floor(t / 3600)}:` : ""}${two(Math.floor((t % 3600) / 60))}:${two(t % 60)}`;
}
/** "21:26:32" in Korea time. */
export const clockKst = (ms) => { const d = new Date(Number(ms) + KST); return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}:${two(d.getUTCSeconds())}`; };
/** 00:00 KST of the day that holds ``ms`` (UTC ms). */
export const kstMidnight = (ms) => Math.floor((Number(ms) + KST) / D) * D - KST;

// ---------------------------------------------------------------- D11
/** True when a position must be counted only (the server's flag, or a DeepSeek one without its money). */
export const hiddenPos = (p) => !!p && (!!p.hidden || (p.kind === "ds" && (p.qty == null || p.entry == null)));
/** True when a closed trade (an /api/fills row or a /api/trades row) of account ``a`` must be counted only: a DeepSeek
 *  account while the snapshot hides its money (dsMoney false), or a row whose money the server left out. */
export function hiddenFill(f, a, dsMoney) {
  const ds = (a && a.kind === "ds") || /^(ds-|base-ds-)/.test(String((f && f.account) || (a && a.id) || ""));
  return ds && (!dsMoney || !f || f.pnl == null);
}

// ---------------------------------------------------------------- names
/** The account's line: the 15분 chip, the strategy's Korean name, the role's short chip ("1/4", "동전" ...). */
export function acctLabel(a, o = {}) {
  if (!a) return h("span", {class: "an"}, "—");
  const name = LK.stratKo(a.name);
  return h("span", {class: ["an", "tm-an"], title: `${name} · ${tfKo(a.tf)} · ${ROLE_SHORT[a.role] || ""} · ${a.id}`},
    a.tf ? h("span", {class: "an-tf"}, tfKo(a.tf)) : null, h("span", {class: "an-n"}, name),
    o.role === false ? null : h("span", {class: ["tm-role", `r-${a.role}`]}, ROLE_SHORT[a.role] || a.role || ""));
}
/** "롱" / "숏" tag (components.css .side). */
export const sideTag = (side) => h("span", {class: ["side", Number(side) > 0 ? "long" : "short"]}, sideKo(side));

// ---------------------------------------------------------------- ages: "6s" / "4m" / "2h" against the server clock
export function age(ms, now = serverNow()) {
  const t = Math.max(0, Math.floor((now - Number(ms)) / 1000));
  if (!Number.isFinite(t)) return "—";
  return t < 60 ? `${t}s` : t < 3600 ? `${Math.floor(t / 60)}m` : t < 86400 ? `${Math.floor(t / 3600)}h` : `${Math.floor(t / 86400)}d`;
}
/** An age cell that ages() repaints every second (text only, never motion). */
export const ageCell = (ms) => h("span", {class: "tm-age num", dataset: {t: String(ms)}, title: `${fmt.kst(ms)} KST`}, age(ms));
export function ages(root) {
  const now = serverNow();
  for (const el of root.querySelectorAll(".tm-age")) {
    if (!el.dataset || el.dataset.t == null) continue;
    const t = age(Number(el.dataset.t), now);
    if (el.textContent !== t) el.textContent = t;
  }
}

// ---------------------------------------------------------------- the panel
/** panel(title, {sub, lead: [el], acts: [el], cls, label, scroll, tip}, ...kids) -> section.tm-p with .head .body .sub */
export function panel(title, o = {}, ...kids) {
  const sub = h("span", {class: "tm-phs"}, o.sub || "");
  const head = h("div", {class: "tm-ph"}, h("h2", {title: o.tip || null}, title), ...(o.lead || []), sub, h("span", {class: "grow"}), ...(o.acts || []),
    h("i", {class: "tm-uline", "aria-hidden": "true"}));
  const body = h("div", {class: ["tm-pb", o.scroll ? "scroll" : ""]}, kids);
  const el = h("section", {class: ["tm-p", o.cls || ""], "aria-label": o.label || title}, head, body);
  el.head = head; el.body = body; el.sub = sub;
  return el;
}

const PING_GAP_MS = 1200;
/** A panel REALLY received new data: the light runs along its head's underline once (at most every 1.2 s); nothing
 *  under reduced motion or on a hidden page; never from a timer. */
export function ping(el) {
  const u = el && el.head && el.head.querySelector(".tm-uline");
  if (!u || reduced() || !visible()) return;
  const now = Date.now();
  if (now - (el._ping || 0) < PING_GAP_MS) return;
  el._ping = now;
  u.classList.remove("run"); void u.offsetWidth; u.classList.add("run");
}

/** ratioBar([{key, label, tone}], {label, cls}) -> element with .set(counts, fmtFn): the segment widths follow the
 *  shares (a CSS transition, off under reduced motion), the legend says each share; no counts: a grey bar and "—". */
export function ratioBar(parts, o = {}) {
  const segs = parts.map((p) => h("i", {class: ["tm-rb-s", p.tone], style: {width: (100 / parts.length).toFixed(2) + "%"}}));
  const labs = parts.map((p) => h("span", {class: ["tm-rb-l", p.tone]}, p.label, " ", h("b", {class: "num"}, "—")));
  const el = h("div", {class: ["tm-rb", o.cls || ""], role: "img", "aria-label": o.label || "비율"},
    h("div", {class: "tm-rb-t"}, segs), h("div", {class: "tm-rb-k"}, labs));
  el.set = (counts, fmtFn) => {
    const tot = parts.reduce((s, p) => s + (Number(counts && counts[p.key]) || 0), 0);
    el.classList.toggle("none", !tot);
    parts.forEach((p, i) => {
      const n = Number(counts && counts[p.key]) || 0, sh = tot ? n / tot : 1 / parts.length;
      segs[i].style.width = (sh * 100).toFixed(2) + "%";
      labs[i].lastChild.textContent = tot ? (fmtFn ? fmtFn(n, sh) : fmt.pct(sh * 100, false, 0)) : "—";
    });
    el.setAttribute("aria-label", `${o.label || "비율"}: ${parts.map((p, i) => `${p.label} ${labs[i].lastChild.textContent}`).join(", ")}`);
  };
  return el;
}

/** "불러오지 못함 · 체결 기록 · 3분 전 자료 [다시 시도]": a failed load is never shown as "없음" or as a zero. */
export function failNote(what, o = {}) {
  return h("div", {class: "tm-fail", role: "status"}, h("b", null, "불러오지 못함"),
    h("span", null, ` · ${what} · ${o.since ? `${fmt.ago(o.since, serverNow())} 자료` : "받은 자료 없음"}`),
    h("span", {class: "muted"}, " · 잠시 뒤 저절로 다시 받습니다"),
    o.retry ? h("button", {type: "button", class: "tm-retry", onclick: o.retry}, "다시 시도") : null);
}

/** The terminal's one caption line (owners 10/06: said once, not under every panel). */
export const FOOT = "모의 · 실제 시세 · 닫힌 거래 손익은 수수료·펀딩·슬리피지 포함 · 열린 포지션은 마크 가격 기준 미실현 (나갈 때 수수료 전) · "
  + "증거금·크기·청산가는 진입 때 기준 · 주문 버튼 없음 · 딥시크 금액을 숨기는 설정이면 딥시크는 개수만";

// ================================================================ realized P&L (pure, no DOM)
/** /api/pnl (hours: [[utc hour START ms, sum, n, wins]]) -> the rule bot's termpnl shape {start, now, hours: [[hour END ms,
 *  pnl, trades, wins, losses]]}. */
export function fromApi(d, startMs, nowMs) {
  const hours = ((d && d.hours) || []).map((r) => {
    const n = Number(r[2]) || 0, w = Number(r[3]) || 0;
    return [Number(r[0]) + H, Number(r[1]) || 0, n, w, Math.max(0, n - w)];
  });
  return {start: Number(startMs) || (hours.length ? hours[0][0] - H : nowMs - H), now: Number(nowMs), from: 0, hours};
}
/** The bucket size for a span: 1 hour up to 3 days, 4 hours up to 14 days, then 1 day. */
export const pickStep = (spanMs) => (spanMs <= 3 * D ? H : spanMs <= 14 * D ? 4 * H : D);
/** The END of the KST-aligned bucket of ``step`` ms that holds the instant ``t``. */
export const bucketEnd = (t, step) => Math.ceil((t + KST) / step) * step - KST;
export const WINDOWS = [{id: "24h", ko: "24시간", ms: D}, {id: "7d", ko: "7일", ms: 7 * D}, {id: "30d", ko: "30일", ms: 30 * D}, {id: "all", ko: "전체", ms: null}];
/** The windows worth offering: each only when shorter than what there is to show (else it would equal 전체). */
export const windowsFor = (spanMs) => WINDOWS.filter((w) => w.ms == null || spanMs > w.ms * 1.15);

/**
 * series(d, windowMs) -> {x0, x1, step, pts: [[t, cum]], bars: [{t0, t1, pnl, n, w, l, cum}], trades, wins, losses, total,
 * mdd, lo, hi, empty}: the cumulative realized line from 0 at the window's start, its buckets, the deepest fall of the
 * hourly cumulative line from its earlier top (USDT, 0 or more). An hour without a closed trade is flat; the last point
 * is now; nothing at all is "empty" (the caller says so, never a flat line).
 */
export function series(d, windowMs = null) {
  const now = Number(d.now), hours = Array.isArray(d.hours) ? d.hours : [];
  const seasonStart = Math.max(Number(d.start) || 0, Number(d.from) || 0);
  const x0 = windowMs ? Math.max(seasonStart, Math.floor((now - windowMs) / H) * H) : seasonStart || (hours.length ? hours[0][0] - H : now - H);
  const x1 = now;
  const step = pickStep(x1 - x0);
  let trades = 0, wins = 0, losses = 0, total = 0;
  const rows = [];
  for (const r of hours) {
    const t = Number(r[0]);
    if (!(t > x0)) continue;
    rows.push({t, pnl: Number(r[1]) || 0, n: Number(r[2]) || 0, w: Number(r[3]) || 0, l: Number(r[4]) || 0});
  }
  const map = new Map();
  for (const r of rows) {
    const e = Math.min(bucketEnd(r.t, step), x1);
    const b = map.get(e) || {t1: e, pnl: 0, n: 0, w: 0, l: 0};
    b.pnl += r.pnl; b.n += r.n; b.w += r.w; b.l += r.l;
    map.set(e, b);
    trades += r.n; wins += r.w; losses += r.l; total += r.pnl;
  }
  const bars = [...map.values()].sort((a, b) => a.t1 - b.t1);
  let cum = 0;
  const pts = [[x0, 0]];
  for (const b of bars) { b.t0 = Math.max(x0, b.t1 - step); cum += b.pnl; b.cum = cum; pts.push([b.t1, cum]); }
  if (pts[pts.length - 1][0] < x1) pts.push([x1, cum]);
  let c = 0, peak = 0, mdd = 0;
  for (const r of rows.sort((a, b) => a.t - b.t)) { c += r.pnl; if (c > peak) peak = c; if (peak - c > mdd) mdd = peak - c; }
  let lo = 0, hi = 0;
  for (const p of pts) { if (p[1] < lo) lo = p[1]; if (p[1] > hi) hi = p[1]; }
  return {x0, x1, step, pts, bars, trades, wins, losses, total, mdd, lo, hi, empty: !rows.length};
}

/** Time ticks strictly inside (x0, x1): hours while the span is short, days after; at most ``max``. */
export function timeTicks(x0, x1, max, fmtHm, fmtMd) {
  const span = x1 - x0, out = [];
  if (!(span > 0) || max < 1) return out;
  const steps = span <= 3 * D ? [3 * H, 6 * H, 12 * H, D] : [D, 2 * D, 3 * D, 7 * D, 14 * D];
  const st = steps.find((s) => span / s <= max) || steps[steps.length - 1];
  const margin = span * 0.07;
  for (let t = Math.ceil((x0 + margin + KST) / st) * st - KST; t < x1 - margin * 2.4; t += st) {
    const midnight = (t + KST) % D === 0;
    out.push({t, label: span > 3 * D || midnight ? fmtMd(t) : fmtHm(t)});
  }
  return out;
}
/** The x-axis ticks that fit between the left label and "지금" without touching either or each other. */
export function axisTicks(ta, tb, pw, fpx, leftLen, fmtHm, fmtMd) {
  const cw = fpx * 0.62, tickW = 5 * cw, gap = 8;
  const X = (t) => 4 + ((t - ta) / Math.max(1, tb - ta)) * pw;
  const minX = 4 + leftLen * cw + gap + tickW / 2;
  const maxX = pw + 4 - 2 * fpx - gap - tickW / 2;
  const out = [];
  for (const k of timeTicks(ta, tb, Math.max(2, Math.floor(pw / (tickW + 26))), fmtHm, fmtMd)) {
    const x = X(k.t);
    if (x < minX || x > maxX) continue;
    if (out.length && x - out[out.length - 1].x < tickW + 10) continue;
    out.push({...k, x});
  }
  return out;
}

/** Today's realized numbers from the hourly rows (the same rows as the line: they can never disagree). */
export function todayOf(d, nowMs) {
  const t0 = kstMidnight(nowMs);
  let n = 0, w = 0, l = 0, pnl = 0;
  for (const r of (d && d.hours) || []) if (Number(r[0]) > t0) { pnl += Number(r[1]) || 0; n += Number(r[2]) || 0; w += Number(r[3]) || 0; l += Number(r[4]) || 0; }
  return {n, w, l, pnl};
}

/**
 * calDays(days, startMs, nowMs) -> {label, cells: [{pad} | {ms, d, state: "before"|"done"|"today"|"future", v, n, w}]}:
 * Monday-first weeks from the week of max(start, now − 34 days) to the week of now; a day with a record carries its
 * realized sum, a done day without one has v null ("기록 없음", never a zero). days: /api/pnl [[kst day ms, sum, n, wins]].
 */
export function calDays(days, startMs, nowMs) {
  const by = new Map(((days || [])).map((r) => [Number(r[0]), r]));
  const today = kstMidnight(nowMs), first = kstMidnight(Math.max(Number(startMs) || nowMs, nowMs - 34 * D));
  const dow = (ms) => (new Date(ms + KST).getUTCDay() + 6) % 7;          // Monday 0
  const from = first - dow(first) * D, to = today + (6 - dow(today)) * D;
  const start = kstMidnight(Number(startMs) || nowMs);
  const cells = [];
  for (let t = from; t <= to; t += D) {
    if (t < first) { cells.push({pad: true}); continue; }
    const r = by.get(t);
    const state = t < start ? "before" : t > today ? "future" : t === today ? "today" : "done";
    const dd = new Date(t + KST);
    cells.push({ms: t, d: dd.getUTCDate(), state, v: r ? Number(r[1]) || 0 : null, n: r ? Number(r[2]) || 0 : 0, w: r ? Number(r[3]) || 0 : 0});
  }
  const ym = (ms) => { const x = new Date(ms + KST); return {y: x.getUTCFullYear(), m: x.getUTCMonth() + 1}; };
  const a = ym(first), b = ym(today);
  const label = a.y === b.y && a.m === b.m ? `${a.y}.${two(a.m)}` : `${a.y}.${two(a.m)} – ${b.m}월`;
  return {label, cells};
}

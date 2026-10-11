// 설치 뒤 진입만 (owners 10/11: "설치 뒤(10월 11일 이후)에 들어간 것만 보기"): one per-device view switch. The league was
// installed on 10/11 and replayed from 10/01, so positions the replay opened still show as open with old entry times.
// With the switch on, every list of OPEN POSITIONS and of CLOSED TRADES on 포지션 · 터미널 · 체결 기록 · 순위표 · 계좌
// keeps only what was ENTERED at or after the install time (the snapshot's ``started_ms``: league meta, written when the
// engine first started; lk.js catchingUp and status.js read the same field), and the counts and sums next to those lists
// are recomputed over what is kept and say "설치 뒤만".
// A VIEW FILTER ONLY: rankings, wallets, 잔고 수익률, the checkpoint (점검) numbers and the coin-flip comparisons stay the full
// record from 10/01, and the bar that holds the switch says so. Nothing here changes what the engine or the server does.
// Per browser (dom.js local: try/catch inside); a browser that cannot store it keeps the choice for this page only (until
// a reload) and the switch says so. Hidden while the snapshot has no started_ms. app.js remounts the screen when the
// switch changes (onAfterChange) and repaints the bars on a new snapshot; the pressed switch keeps its place on the
// screen (no jump to the top) and the focus.
//   installMs(doc?)       the install time (ms) from doc, else the shared snapshot, else the last /api/positions answer
//   afterOn(doc?)         the switch is on AND the install time is known (the only test the screens use)
//   enteredAfter(ms, cut) an entry time at or after the cut (a missing time never counts as after)
//   keepPos(p) keepFill(f) openAfter(a)    one /api/positions entry · one closed trade · a league account's open position
//   afterPositions(doc)   an /api/positions answer with the positions filtered and the counts recomputed (+ .after)
//   afterFills(rows) afterBook(book)       /api/fills rows · an /api/trades/<id> answer (its trades only; equity stays)
//   afterBar(o) afterTag() afterSuffix()   the switch with its note · the "설치 뒤만" chip · " · 설치 뒤만" for a text
//   afterEmpty(head, note) beforeChip(a)   a list the switch emptied (+ the "모두 보기" button) · in place of a hidden pill
import {h, local} from "./dom.js";
import * as fmt from "./fmt.js";
import {league} from "./lk.js";
import {positionsDoc} from "./poskit.js";

const KEY = "after";
const fin = (x) => (x == null || x === "" || typeof x === "boolean" || !Number.isFinite(Number(x)) ? null : Number(x));

// ---------------------------------------------------------------- the state
/** The install time (ms): doc.started_ms when doc carries one, else the shared snapshot's (league.json meta), else the
 *  last /api/positions answer's (the same field, dash.py positions_doc); null when none of them has it. */
export function installMs(doc) {
  for (const d of [doc, league(), positionsDoc()]) {
    const v = d ? fin(d.started_ms) : null;
    if (v != null && v > 0) return v;
  }
  return null;
}
let mem = null;                 // the choice while this browser cannot store it (blocked storage): this page only
/** The viewer asked for it (this device; a blocked storage: this page, until a reload). */
export const afterWanted = () => (mem != null ? mem : local.get(KEY, false) === true);
/** The choice could not be stored (blocked storage): it lasts until the page is reloaded. */
export const afterVolatile = () => mem != null;
/** The switch is on and the install time is known: lists keep only what was entered at or after installMs(). */
export const afterOn = (doc) => afterWanted() && installMs(doc) != null;

const subs = new Set();
/** fn(on) after every change of the switch; returns the unsubscribe (app.js remounts the screen). */
export function onAfterChange(fn) { subs.add(fn); return () => subs.delete(fn); }
let focusNext = false;
let anchor = null;              // {top} where the pressed switch was on the screen, or {y} the page's scroll position
/** Turn the switch on / off. o.focus: the next bar built takes the focus (it was pressed on the screen being remounted);
 *  o.from: the pressed button (the next bar is scrolled to the same place on the screen, so it does not jump);
 *  o.keepY: the remounted screen keeps the page's scroll position (a "모두 보기" button inside a list). */
export function setAfter(on, o = {}) {
  const v = !!on;
  if (v === afterWanted()) return;
  local.set(KEY, v);
  mem = (local.get(KEY, false) === true) === v ? null : v;           // not stored: keep it for this page
  focusNext = !!o.focus;
  anchor = null;
  if (o.from && o.from.getBoundingClientRect) { try { anchor = {top: o.from.getBoundingClientRect().top}; } catch (e) { anchor = null; } }
  else if (o.keepY && typeof window !== "undefined") anchor = {y: window.scrollY || 0};
  for (const fn of [...subs]) { try { fn(v); } catch (e) { console.error(e); } }
  syncAfter();
}
/** Scroll so ``btn`` sits where the pressed switch was (a.top px from the window's top), or back to the page's scroll
 *  position (a.y). The screen is remounted from the top and its parts fill in over a second or two, so this runs again
 *  a few times, and stops as soon as the viewer scrolls, taps or types themselves. */
function keepPlace(btn, a) {
  if (typeof window === "undefined" || typeof window.scrollBy !== "function") return;
  let stop = false;
  const quit = () => { stop = true; };
  const evs = ["wheel", "touchstart", "pointerdown", "keydown"];
  for (const e of evs) window.addEventListener(e, quit, {once: true, passive: true});
  const pin = () => {
    if (stop || !btn.isConnected || !btn.getBoundingClientRect) return;
    const dy = a.y != null ? a.y - (window.scrollY || 0) : btn.getBoundingClientRect().top - a.top;
    if (Math.abs(dy) > 1) window.scrollBy(0, dy);
  };
  const waits = [0, 60, 200, 450, 900, 1600, 2600];
  waits.forEach((ms, i) => setTimeout(() => {
    pin();
    if (i === waits.length - 1) for (const e of evs) window.removeEventListener(e, quit);
  }, ms));
}

// ---------------------------------------------------------------- the filters (pure)
/** An entry time at or after the cut; a missing or broken time never counts as "after". */
export const enteredAfter = (ms, cut) => { const t = fin(ms); return t != null && cut != null && t >= cut; };
/** One /api/positions entry (or a league account's ``open``) stays: the switch is off, or it was entered after the install. */
export const keepPos = (p, cut = afterOn() ? installMs() : null) => cut == null || (!!p && enteredAfter(p.since, cut));
/** One closed trade (/api/fills row, /api/trades row) stays: the switch is off, or it was ENTERED after the install. */
export const keepFill = (f, cut = afterOn() ? installMs() : null) => cut == null || (!!f && enteredAfter(f.entry_time, cut));
/** A league account's open position as the lists show it: a.open, or null when the switch hides it (entered before the
 *  install). The ranking itself never asks this (it reads a.open: the full record). */
export const openAfter = (a, cut = afterOn() ? installMs() : null) => (a && a.open && keepPos(a.open, cut) ? a.open : null);
/** The open position is there but hidden by the switch (entered before the install). */
export const openBefore = (a, cut = afterOn() ? installMs() : null) => !!(a && a.open && !keepPos(a.open, cut));

/** /api/positions counts over a list of positions (the server's shape: dash.py positions_doc). */
export function countsOf(list) {
  const c = {open: 0, long: 0, short: 0, hidden: 0, by_coin: {}, by_role: {}, by_kind: {}};
  for (const p of list || []) {
    const side = Number(p.side) > 0 ? "long" : "short";
    c.open += 1;
    c[side] += 1;
    c.hidden += p.hidden ? 1 : 0;
    const k = c.by_coin[p.coin] || (c.by_coin[p.coin] = {long: 0, short: 0});
    k[side] += 1;
    c.by_role[p.role] = (c.by_role[p.role] || 0) + 1;
    c.by_kind[p.kind] = (c.by_kind[p.kind] || 0) + 1;
  }
  return c;
}
/** An /api/positions answer as the lists show it: unchanged while the switch is off (or the time is unknown); else a new
 *  object (the shared answer is never modified) with the positions entered after the install, the counts recomputed over
 *  them, and ``after`` = {ms, before: [{id, coin, side, since}] (the ones left out, for "설치 전 진입이라 숨김")}. */
export function afterPositions(doc, on = afterOn(doc)) {
  if (!doc || doc.status || !Array.isArray(doc.positions) || !on) return doc;
  const cut = installMs(doc);
  if (cut == null) return doc;
  const keep = [], before = [];
  for (const p of doc.positions) (enteredAfter(p && p.since, cut) ? keep : before).push(p);
  return {...doc, positions: keep, counts: countsOf(keep),
    after: {ms: cut, before: before.map((p) => ({id: p.id, coin: p.coin, side: p.side, since: p.since, role: p.role, kind: p.kind}))}};
}
/** /api/fills rows as the lists show them (entered after the install while the switch is on). */
export function afterFills(rows, on = afterOn()) {
  if (!Array.isArray(rows) || !on) return rows;
  const cut = installMs();
  return cut == null ? rows : rows.filter((f) => keepFill(f, cut));
}
/** An /api/trades/<id> answer with its trades filtered; the equity line (the wallet: the full record) stays whole. */
export function afterBook(book, on = afterOn()) {
  if (!book || !Array.isArray(book.trades) || !on) return book;
  const cut = installMs();
  return cut == null ? book : {...book, trades: book.trades.filter((t) => keepFill(t, cut)), all_trades: book.trades.length};
}

// ---------------------------------------------------------------- the pieces on the page
const startKo = () => { const lg = league(); return lg && fin(lg.start_ms) ? fmt.mmdd(lg.start_ms) : "10/01"; };
/** "설치 뒤만": the chip next to a count or a sum the switch recomputed (null while off). */
export const afterTag = (doc) => (afterOn(doc) ? h("span", {class: "pp thin kp-after-tag", title: `설치(${fmt.kst(installMs(doc))} KST) 뒤에 들어간 것만 셉니다 · 끄면 10/01부터 전부`}, "설치 뒤만") : null);
/** " · 설치 뒤만" for a line of text ("" while off). */
export const afterSuffix = (doc) => (afterOn(doc) ? " · 설치 뒤만" : "");
/** The button that turns the switch off ("모두 보기"), for a list the switch left empty. */
export const afterOffBtn = (o = {}) => h("button", {type: "button", class: ["btn-line", "kp-after-off", o.sm ? "sm" : ""],
  onclick: () => setAfter(false, {keepY: true})}, "모두 보기 (설치 뒤 진입만 끄기)");
/**
 * afterEmpty(head, note, {cls, sm}) -> the empty state of a list the switch emptied although the server sent entries:
 * "설치 뒤에 들어간 … 아직 없습니다" (head), why (note: how many were entered before the install), and the button
 * "모두 보기 (설치 뒤 진입만 끄기)". Never "없습니다" alone: the bot has positions or trades, they are only hidden.
 */
export function afterEmpty(head, note, o = {}) {
  return h("div", {class: ["kp-after-empty", o.cls], role: "status"}, h("b", null, head), note ? h("span", null, note) : null, afterOffBtn(o));
}
/** "설치 전 진입 · 숨김": where an open-position pill would be, when the switch hides that position (null otherwise). */
export const beforeChip = (a, cut) => (openBefore(a, cut) ? h("span", {class: "pp thin kp-after-pre",
  title: `열린 포지션이 설치(${fmt.kst(installMs())} KST) 전에 들어간 것이라 '설치 뒤 진입만' 보기에서 숨겼습니다 (끄면 보임)`}, "설치 전 진입 · 숨김") : null);

const BARS = new Set();
/**
 * afterBar({cls, also}) -> the switch "○ 설치 뒤 진입만 (10/11 21:03 이후)" and its note "순위·잔고·점검은 10/01부터 전체
 * 기록" (also: more names for the note, e.g. "수익 차트"); hidden while the install time is unknown. el.repaint(doc?) (doc:
 * an answer that carries started_ms, e.g. /api/positions, for a page whose snapshot has not come yet).
 */
export function afterBar(o = {}) {
  const btn = h("button", {type: "button", class: "dl-tog kp-after-tog", "aria-pressed": "false",
    onclick: () => setAfter(!afterWanted(), {focus: true, from: btn})});
  const note = h("span", {class: "kp-after-note"});
  const el = h("div", {class: ["kp-after", o.cls], role: "group", "aria-label": "설치 뒤 진입만 보기"}, btn, note);
  el.repaint = (doc) => {
    if (doc !== undefined) el._doc = doc;                            // a screen's own answer may carry started_ms first
    const ms = installMs(el._doc);
    el.hidden = ms == null;
    const on = afterOn(el._doc);
    btn.setAttribute("aria-pressed", String(on));
    btn.textContent = ms == null ? "설치 뒤 진입만" : `설치 뒤 진입만 (${fmt.kst(ms)} 이후)`;
    btn.title = ms == null ? "" : `${on ? "켜짐" : "꺼짐"} · 켜면 열린 포지션과 체결 목록에 설치(${fmt.kst(ms)} KST) 뒤에 들어간 것만 보입니다. ` +
      `${startKo()}부터 다시 돌린 기록으로 열린 포지션은 숨깁니다. ` +
      (afterVolatile() ? "이 브라우저는 저장이 막혀 있어 새로 고치면 처음대로 돌아갑니다." : "이 기기에만 기억합니다.");
    el.classList.toggle("on", on);
    const what = ["순위", "잔고", ...(o.also || []), "점검"].join("·");
    note.textContent = `보기만 바뀝니다 · ${what}은 ${startKo()}부터 전체 기록` + (afterVolatile() ? " · 저장이 막혀 새로 고치면 처음대로" : "");
    note.title = `보기만 거릅니다: 순위·잔고·잔고 수익률·점검 숫자·동전 비교는 늘 ${startKo()}부터의 전체 기록입니다.`;
  };
  el.repaint();
  for (const b of [...BARS]) if (!b.isConnected) BARS.delete(b);     // the previous screen's bar is gone by now
  BARS.add(el);
  if (anchor) { const a = anchor; anchor = null; keepPlace(btn, a); }  // the switch was just pressed: same place on screen
  if (focusNext) {                                                   // ... and the focus stays on it
    focusNext = false;
    setTimeout(() => { if (btn.isConnected && typeof btn.focus === "function") btn.focus({preventScroll: true}); }, 0);
  }
  return el;
}
/** Repaint every bar on the page (a new snapshot may bring the install time, or the switch changed). */
export function syncAfter() { for (const b of BARS) b.repaint(); }

// Shared components. All take plain data and return DOM nodes built with h()/s() (text is never parsed as HTML).
// HONESTY helpers live here too: assume() (the money caption), refNote() (comparison = 참고 until the verdict),
// smallSample() (표본 적음), notYet() (수집 전). See CONTRACT.md for when each one is required.
import {h, s, $, $$, clear, put, local} from "./dom.js";
import {num, int, mmdd, acctParts, ago} from "./fmt.js";
import {store} from "./store.js";
import {countTo, swap, expand, popBubble, reduced, drawIn, fadeIn, shimmer} from "./motion.js";

// ---------------------------------------------------------------- captions (non-negotiable rules)
export const ASSUME_KO = "모의 · 실제 시세 · 수수료·펀딩·슬리피지 포함";
export const ASSUME_OPEN_KO = "모의 · 실제 시세 · 마크 가격 기준 미실현(나갈 때 수수료 전) · 주문 버튼 없음";
/** The caption under every money number. kind "open": unrealized P&L (before the exit fee, so it says so). */
export function assume(kind = "closed", extra) {
  return h("p", {class: "assume"}, kind === "open" ? ASSUME_OPEN_KO : ASSUME_KO, extra ? ` · ${extra}` : null);
}
// ---------------------------------------------------------------- say it once (owners 10/06 ~14:00)
// "작은 글씨가 패널마다 반복된다": a screen whose cards all share the same assumptions prints them ONCE, in one slim
// line (assumeLine), and each money card keeps an ⓘ (infoTip) whose tooltip carries that card's exact note.
/** Closed and open money on one screen, in one line. */
export const ASSUME_ALL_KO = "모의 · 실제 시세 · 닫힌 거래 손익은 수수료·펀딩·슬리피지 포함 · 열린 포지션은 마크 가격 기준 미실현(나갈 때 수수료 전) · 주문 버튼 없음";
/** The screen's one caption line. kinds: "closed" / "open" / both (the default); extra: the screen's own last words. */
export function assumeLine(kinds = ["closed", "open"], extra) {
  const k = new Set(kinds);
  const text = k.has("closed") && k.has("open") ? ASSUME_ALL_KO : k.has("open") ? ASSUME_OPEN_KO : ASSUME_KO;
  return h("p", {class: "assume once"}, text, extra ? ` · ${extra}` : null);
}
let tipNow = null;
function tipClose() {
  if (!tipNow) return;
  tipNow.b.setAttribute("aria-expanded", "false");
  tipNow.pop.remove();
  tipNow = null;
}
function tipWire() {
  if (tipWire.done || typeof document === "undefined") return;
  tipWire.done = true;
  document.addEventListener("pointerdown", (e) => { if (tipNow && !tipNow.pop.contains(e.target) && !tipNow.b.contains(e.target)) tipClose(); }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") tipClose(); });
  window.addEventListener("hashchange", tipClose);
  window.addEventListener("scroll", tipClose, true);
  window.addEventListener("resize", tipClose);
}
/**
 * infoTip(text, label) -> an ⓘ button for a card / panel head: its tooltip is the card's own note (hover on a PC); a
 * tap opens the same words in a small bubble (phones), a tap elsewhere or Escape closes it. .set(text) changes them.
 */
export function infoTip(text, label = "설명") {
  const b = h("button", {type: "button", class: "itip", "aria-expanded": "false"}, "ⓘ");
  b.set = (t) => {
    b.title = t;
    b.setAttribute("aria-label", `${label}: ${t}`);
    if (tipNow && tipNow.b === b) tipNow.pop.textContent = t;
  };
  b.set(text);
  b.addEventListener("click", (e) => {
    e.stopPropagation();
    const same = tipNow && tipNow.b === b;
    tipClose();
    if (same) return;
    tipWire();
    const pop = h("div", {class: "itip-pop", role: "tooltip"}, b.title);
    document.body.append(pop);
    const r = b.getBoundingClientRect(), pw = pop.offsetWidth, ph = pop.offsetHeight;
    pop.style.left = Math.round(Math.max(16, Math.min(innerWidth - 16 - pw, r.left + r.width / 2 - pw / 2))) + "px";
    pop.style.top = Math.round(r.bottom + 6 + ph > innerHeight - 8 ? Math.max(8, r.top - 6 - ph) : r.bottom + 6) + "px";
    b.setAttribute("aria-expanded", "true");
    tipNow = {b, pop};
  });
  return b;
}
// ---------------------------------------------------------------- the verdict's method (server facts, never typed in)
// /api/summary restart carries method_ko / n_bots / family_alpha (paperbot/dash/app.py verdict_method, from
// checkpoint.N_BOTS and FAMILY_ALPHA); core/shell.js hands it here. Before it arrives the words stay neutral.
let METHOD = null;
export function setMethod(rs) {
  if (rs && (rs.method_ko || rs.n_bots)) METHOD = {method_ko: rs.method_ko || null, n_bots: Number(rs.n_bots) || null, family_alpha: rs.family_alpha || null};
}
/** "같은 봉 동전 봇 N개" with the server's own count N; "같은 봉 동전 봇" until the server says it. */
export const botsKo = () => (METHOD && METHOD.n_bots ? `같은 봉 동전 봇 ${int(METHOD.n_bots)}개` : "같은 봉 동전 봇");
/** The verdict's method in one line: the server's method_ko, else neutral words (no typed-in count or error rate). */
export const methodKo = () => (METHOD && METHOD.method_ko ? METHOD.method_ko : "같은 봉 동전 봇과 비교 · 묶음마다 따로 운 보정");
/** Under any comparison with the coin flips before the checkpoint verdict. verdictTs: the next verdict (ms): after
 *  the first verdict (11/04) it is the second (12/04), so the words say '30일마다 (다음 MM/DD)', never '30일째 (12/04)'.
 *  A verdict time already past is the verdict-day clock's 'due' checkpoint (its result is not stored yet): said so,
 *  never '다음' for a time that has gone by. */
export function refNote(verdictTs, extra) {
  const when = !verdictTs ? "" : verdictTs <= Date.now() ? ` (${mmdd(verdictTs)} 09:00 판정 결과를 기다리는 중)` : ` (다음 ${mmdd(verdictTs)} 09:00)`;
  return h("p", {class: "refnote"}, h("b", null, "참고"), " · 판정은 30일마다", when,
    ` 계좌마다 ${botsKo()}와 비교해서 합니다. 지금 비교는 합격·불합격을 뜻하지 않습니다.`,
    extra ? ` ${extra}` : null);
}
/** '표본 적음' pill when n is below min. The default is the verdict's own floor for trade counts (checkpoint.MIN_TRADES
 *  = 30: an account under 30 trades is '보류' on the day); meetings and graded calls pass their own smaller min. */
export function smallSample(n, min = 30) {
  return n != null && n < min ? h("span", {class: "pp thin", title: `${min}건 미만: 우연일 수 있습니다`}, "표본 적음") : null;
}
/** An account's name for a list: the timeframe first in a box that never shrinks, then the name (cut with … on a
 *  phone, never the timeframe). Extras with their own label_ko show that label. */
export function acctLabel(a) {
  if (a && a.label_ko) return h("span", {class: "an"}, h("span", {class: "an-n"}, a.label_ko));
  const p = acctParts(a);
  return h("span", {class: "an"}, p.tf ? h("span", {class: "an-tf"}, p.tf) : null, h("span", {class: "an-n"}, p.name));
}
/** '수집 전': a number this dashboard cannot read yet (no endpoint or no record). Never a made-up value. */
export const notYet = (label = "수집 전", title) => h("span", {class: "notyet", title: title || "서버가 아직 이 값을 보내지 않습니다"}, label);

// ---------------------------------------------------------------- small pieces
export const plate = (text, attrs) => h("span", {class: "plate", ...attrs}, text);
export const pill = (text, cls = "", title) => h("span", {class: ["pp", cls], title}, text);
/** LIVE / 회의 중: call only from real state (a meeting running now, a fresh stream). */
export const livePill = (text = "LIVE") => h("span", {class: "live-pill"}, text);
export const sideTag = (side) => h("span", {class: ["side", Number(side) > 0 ? "long" : "short"]}, Number(side) > 0 ? "롱" : "숏");
export const empty = (text) => h("p", {class: "empty"}, text);
/** A small grey note under a card's content (how to read it, where a number comes from). */
export const note = (...kids) => h("p", {class: "note"}, ...kids);
// ---------------------------------------------------------------- 불러오는 중 / 못 불러옴 / 진짜 없음 (review 10/06)
// Every screen tells three states apart (CONTRACT §1.6: a failed load never reads as '없음'):
//   불러오는 중  shimmer rows (motion.shimmer) while the first answer is on its way;
//   못 불러옴    errorBox (nothing to show yet), or staleNote above the last good data, which stays on screen, dimmed;
//   진짜 없음    the screen's own words (empty), only from a real answer.
// loadState(v, err) names the state; for a store key: loadState(store.get(k), store.meta(k).err).
/** "loading" | "failed" | "stale" | "ok": a value (undefined / null = none yet) and the error of the last try. */
export function loadState(v, err) {
  if (v === undefined || v === null) return err ? "failed" : "loading";
  return err ? "stale" : "ok";
}
/** What went wrong, in the owners' words (core/api.js ApiError kinds). */
export function failKo(err) {
  if (err && err.status === 404) return "이 자료가 서버에 없습니다";
  if (err && err.kind === "timeout") return "서버가 제때 답하지 않았습니다";
  if (err && err.kind === "network") return "서버에 닿지 못했습니다 (연결 끊김)";
  return "불러오지 못했습니다";
}
/** Over the last good data when a refresh failed: '불러오지 못함 · 2분 전 자료' (+ 다시 시도). Dim the data with
 *  dim(el, true) meanwhile. okAt: when that data came (store.meta(k).okAt). */
export function staleNote(err, okAt, retry) {
  return h("div", {class: "failnote", role: "status"}, h("b", null, failKo(err)),
    okAt ? h("span", {class: "muted"}, ` · ${ago(okAt)} 자료를 보여 드립니다`) : null,
    retry ? h("button", {class: "btn-line", type: "button", onclick: retry}, "다시 시도") : null);
}
/** Dims (or undims) data that is older than the last failed refresh. */
export const dim = (el, on) => { if (el && el.classList) el.classList.toggle("is-stale", !!on); return el; };

/** The tries of the boxes drawn into one place (or under one o.id, for a caller that draws a new place each time, like
 *  the router's screen): a load that fails again draws a new box there, and the wait keeps growing instead of starting
 *  over at 5 s (it starts over 3 minutes after the last try). */
const TRIES = new WeakMap();
const TRIES_ID = new Map();
export const RETRY_S = [5, 15, 30, 60];
/**
 * A failed load. With retry (a function; a promise that rejects on failure), the box tries again BY ITSELF after 5,
 * 15, 30 and 60 seconds, then every 60 seconds, while it is on the page (a screen left, or the box replaced by the
 * caller's own drawing, stops it), and says when; 다시 시도 tries now. When a try succeeds and the caller has not drawn
 * over the box, the box takes itself away. o.key: a store key whose next good answer (from any poll) also takes it
 * away. o.auto false: only the button; o.auto true: by itself even for a retry that loads the page again (the caller
 * makes sure it does so only once the server answers). Without retry the box promises nothing.
 */
export function errorBox(err, retry, o = {}) {
  const when = h("span", {class: "errbox-when"});
  const btn = retry ? h("button", {class: "btn-line", type: "button"}, "다시 시도") : null;
  const box = h("div", {class: "errbox", role: "status"}, h("span", null, failKo(err)), when, btn);
  if (!retry) return box;
  // a retry that reloads the whole page is never run by itself (a server that is down would leave the browser's own
  // error page, which never comes back): only the button does it
  const auto = o.auto === true || (o.auto !== false && !(err && err.status === 404) && !/location\.reload/.test(String(retry)));
  let timer = null, busy = false, off = null;
  const gone = () => { clearTimeout(timer); timer = null; if (off) { off(); off = null; } };
  const heal = () => { gone(); if (box.isConnected) box.remove(); if (o.onOk) o.onOk(); };
  const memo = () => {
    const p = o.id || box.parentNode, map = o.id ? TRIES_ID : TRIES;
    if (!p) return null;
    let m = map.get(p);
    if (!m || Date.now() - m.at > 180000) { m = {n: 0, at: Date.now()}; map.set(p, m); }
    return m;
  };
  const plan = () => {
    clearTimeout(timer);
    if (!auto || !box.isConnected) return;
    const m = memo(), s = RETRY_S[Math.min(m ? m.n : 0, RETRY_S.length - 1)];
    when.textContent = ` · ${s}초 뒤 저절로 다시 시도`;
    timer = setTimeout(() => {
      if (!box.isConnected) { gone(); return; }
      if (typeof document !== "undefined" && document.visibilityState === "hidden") { plan(); return; }
      run();
    }, s * 1000);
  };
  const run = async () => {
    if (busy || !box.isConnected) return;
    busy = true; clearTimeout(timer);
    const m = memo();
    if (m) { m.n++; m.at = Date.now(); }
    when.textContent = " · 다시 시도하는 중…";
    if (btn) btn.disabled = true;
    try {
      await retry();
      busy = false;
      if (box.isConnected) heal(); else gone();
    } catch (e) {
      busy = false;
      if (btn) btn.disabled = false;
      if (box.isConnected) plan(); else gone();
    }
  };
  btn.addEventListener("click", run);
  if (o.key) {
    let armed = false;
    off = store.watch(o.key, (v, k, e) => {
      if (!armed) return;
      if (!box.isConnected) { if (box.dataset.placed) gone(); return; }
      if (v !== undefined && !e) heal();
    });
    armed = true;
  }
  // schedule once the caller has put the box on the page (the next tick); a box never placed keeps no timer
  setTimeout(() => { if (box.isConnected) { box.dataset.placed = "1"; plan(); } else gone(); }, 0);
  return box;
}
export const avatar = (label, hue, cls = "") => h("span", {class: ["rav", cls], style: {"--h": hue ?? 210}, "aria-hidden": "true"}, label);

/** A number cell that counts to new values (a money / pct number: give it {format, sign, tone}; flash: true | "accent"
 *  tints it once when the value really changed). */
export function liveNum(value, opts = {}) {
  const el = h(opts.tag || "b", {class: ["num", opts.cls]});
  countTo(el, value, opts);
  el.update = (v) => countTo(el, v, opts);
  return el;
}
/** A number in a view that is drawn again on every update (a list, a card rebuilt from data): it counts from the value
 *  it showed last time (prev) to now and tints once when they differ (opts as liveNum, flash on by default); the first
 *  time (prev null) it simply shows now. Keep prev yourself, e.g. in a Map by key. */
export function numFrom(prev, now, opts = {}) {
  const el = h(opts.tag || "b", {class: ["num", opts.cls]});
  if (prev != null && Number.isFinite(Number(prev)) && now != null) el.dataset.v = String(prev);
  countTo(el, now, {flash: "accent", ...opts});
  return el;
}

export function stat(k, v, sub, attrs) {
  return h("div", {class: "stat", ...attrs}, h("span", {class: "k"}, k), v instanceof Node ? v : h("b", null, v ?? "—"),
    sub != null ? (sub instanceof Node ? sub : h("span", {class: "s"}, sub)) : null);
}
export function kv(pairs) {
  return h("dl", {class: "kv"}, pairs.filter(Boolean).map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, v ?? "—"))));
}

/** card({title, plate, sub, acts:[nodes], cls, hero}, ...children) */
export function card(o = {}, ...kids) {
  const head = (o.title || o.plate || o.acts) ? h("div", {class: "card-h"},
    o.plate ? plate(o.plate) : null, o.title ? h(o.h || "h2", null, o.title) : null,
    o.sub ? h("span", {class: "sub"}, o.sub) : null,
    o.acts ? h("div", {class: "acts"}, o.acts) : null) : null;
  return h("section", {class: ["card", o.hero ? "hero" : "", o.cls], id: o.id, "aria-label": o.label || o.title || o.plate}, head, kids);
}

/** Screen header: h1 + sub line + right-side actions. */
export const screenHead = (title, sub, acts) => h("div", {class: "scr-head"}, h("h1", null, title),
  sub ? h("span", {class: "sub"}, sub) : null, acts ? h("span", {class: "grow"}) : null, acts || null);

// ---------------------------------------------------------------- tabs (segmented, keyboard arrows)
/**
 * seg([{id, label, disabled, title}], value, onChange, {label, scroll}) -> div.seg[role=tablist] with .set(id).
 * Hidden options: just leave them out (features not running yet are not shown at all).
 */
export function seg(options, value, onChange, o = {}) {
  const el = h("div", {class: ["seg", o.scroll ? "scroll" : ""], role: "tablist", "aria-label": o.label || "보기"});
  const btns = options.map((op) => h("button", {type: "button", role: "tab", "aria-selected": String(op.id === value),
    tabindex: op.id === value ? "0" : "-1", disabled: op.disabled || null, title: op.title, dataset: {id: op.id}}, op.label));
  const select = (b, focus) => {
    btns.forEach((x) => { const on = x === b; x.setAttribute("aria-selected", String(on)); x.tabIndex = on ? 0 : -1; });
    if (focus) b.focus();
  };
  btns.forEach((b) => {
    b.addEventListener("click", () => { if (b.disabled) return; select(b, false); onChange && onChange(b.dataset.id); });
    b.addEventListener("keydown", (e) => {
      const en = btns.filter((x) => !x.disabled), i = en.indexOf(b);
      const n = e.key === "ArrowRight" ? en[(i + 1) % en.length] : e.key === "ArrowLeft" ? en[(i - 1 + en.length) % en.length]
        : e.key === "Home" ? en[0] : e.key === "End" ? en[en.length - 1] : null;
      if (n) { e.preventDefault(); select(n, true); onChange && onChange(n.dataset.id); }
    });
  });
  el.append(...btns);
  el.set = (id) => { const b = btns.find((x) => x.dataset.id === id); if (b) select(b, false); };
  return el;
}

// ---------------------------------------------------------------- long text: two lines, then 더 보기
export function moreText(text, lines = 2, cls = "") {
  const body = h("div", {class: ["clamp", cls], style: {"--lines": lines}}, text);
  const btn = h("button", {class: "more", type: "button", hidden: true, "aria-expanded": "false"}, "더 보기");
  const wrap = h("div", {class: "moretext"}, body, btn);
  const check = () => {
    if (btn.getAttribute("aria-expanded") === "true" || !body.isConnected) return;
    btn.hidden = !(body.scrollHeight > body.clientHeight + 2);
  };
  btn.addEventListener("click", () => {
    const open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(open)); btn.textContent = open ? "접기" : "더 보기";
    body.style.setProperty("--full", body.scrollHeight + "px");
    if (open) { body.classList.add("open"); if (reduced()) body.style.setProperty("--full", "none"); }
    else { void body.offsetHeight; body.classList.remove("open"); }
  });
  requestAnimationFrame(check);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(check);
  wrap.check = check;
  return wrap;
}

/** A disclosure: a button that expands / collapses a region smoothly. */
export function disclosure(label, content, open = false) {
  const region = h("div", {class: "region", hidden: !open}, content);
  const btn = h("button", {class: "linkish", type: "button", "aria-expanded": String(open)}, label);
  btn.addEventListener("click", () => {
    const o = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(o)); expand(region, o);
  });
  return h("div", {class: "disclosure"}, btn, region);
}

// ---------------------------------------------------------------- white pixel speech bubble (real lines only)
/** bubble({who, time, text, tail: "tl"|"tr"|"lft", fresh}) — text is a REAL stored line (first sentence is fine). */
export function bubble(o) {
  const el = h("div", {class: ["say", o.tail || "tl", o.cls], style: o.tailAt != null ? {"--tail": o.tailAt + "px"} : null},
    (o.who || o.time) ? h("span", {class: "sh"}, o.who || "", o.who && o.time ? " · " : "", o.time || "") : null, o.text);
  if (o.fresh) popBubble(el);
  return el;
}

// ---------------------------------------------------------------- step strip: lights only real steps
/** stepStrip([{id, label}], {done: ["analysis", ...], now: "challenge"}) — pass only steps that really happened. */
export function stepStrip(steps, state = {}) {
  const done = new Set(state.done || []);
  return h("ol", {class: "steps", "aria-label": state.label || "단계"}, steps.map((st) =>
    h("li", {class: done.has(st.id) ? "done" : st.id === state.now ? "now" : "", "aria-current": st.id === state.now ? "step" : null},
      st.label)));
}

// ---------------------------------------------------------------- gauges (서버·비용)
/** gauge({name, value, unit, cap, ratio, state, mean, note}). value null -> '수집 전'. state: ok|warn|bad (auto from
 *  ratio: < .6 ok, < .85 warn, else bad). */
export function gauge(o) {
  const have = o.value != null && !(typeof o.value === "number" && Number.isNaN(o.value));
  const r = o.ratio != null ? o.ratio : have && o.cap ? Number(o.value) / Number(o.cap) : null;
  const st = !have ? "none" : o.state || (r == null ? "ok" : r < 0.6 ? "ok" : r < 0.85 ? "warn" : "bad");
  const stKo = {ok: "여유", warn: "지켜볼 것", bad: "조치 필요", none: "수집 전"}[st];
  return h("div", {class: ["gauge", st]},
    h("div", {class: "g-top"}, h("span", {class: "g-name"}, o.name), h("span", {class: "g-st"}, stKo),
      h("span", {class: "g-val"}, have ? (o.value instanceof Node ? o.value : String(o.display ?? o.value)) : "—",
        have && o.cap != null ? h("small", null, ` / ${o.capDisplay ?? o.cap}${o.unit ? " " + o.unit : ""}`) : null)),
    r != null ? h("div", {class: "g-bar"}, h("i", {style: {"--v": Math.max(0, Math.min(1, r)) * 100 + "%"}})) : null,
    o.mean ? h("p", {class: "g-mean"}, o.mean) : null);
}

// ---------------------------------------------------------------- lists: never render hundreds of rows at once
/**
 * pager({size, row: (item, i) => Node, empty}) -> {el, set(items)}; shows one page (size rows) and 이전/다음.
 * searchList({items, size, row, match: (item, q) => bool, placeholder, filters: Node}) -> {el, set(items), refresh()}
 */
export function pager(o) {
  const st = {items: [], page: 0};
  const list = h("div", {class: "plist", role: "list"});
  const info = h("span", {class: "pinfo"});
  const prev = h("button", {class: "btn-line", type: "button"}, "이전");
  const next = h("button", {class: "btn-line", type: "button"}, "다음");
  const bar = h("div", {class: "pager"}, prev, info, next);
  const size = o.size || 10;
  const render = (animate) => {
    const pages = Math.max(1, Math.ceil(st.items.length / size));
    st.page = Math.min(st.page, pages - 1);
    const s0 = st.page * size, part = st.items.slice(s0, s0 + size);
    // o.empty: the words of a real empty answer, or a function returning the node to show instead (불러오는 중 /
    // 못 불러옴 while there is no answer yet: a failed load never reads as '없음')
    put(list, part.length ? part.map((it, i) => o.row(it, s0 + i)) : typeof o.empty === "function" ? o.empty() : empty(o.empty || "맞는 항목이 없습니다"));
    info.textContent = st.items.length ? `${num(s0 + 1, 0)}–${num(s0 + part.length, 0)} / ${num(st.items.length, 0)}` : "0 / 0";
    prev.disabled = st.page === 0; next.disabled = st.page >= pages - 1;
    bar.hidden = st.items.length <= size;
    if (animate) swap(list);
  };
  prev.addEventListener("click", () => { st.page--; render(true); });
  next.addEventListener("click", () => { st.page++; render(true); });
  return {el: h("div", {class: "pagerwrap stack tight"}, list, bar),
    set(items, keepPage) { st.items = items || []; if (!keepPage) st.page = 0; render(!keepPage); }, rerender: () => render(false)};
}
export function searchList(o) {
  // items undefined: no answer yet, so the list shimmers (불러오는 중) instead of saying its empty words
  const st = {items: o.items, q: ""};
  const input = h("input", {class: "search", type: "search", placeholder: o.placeholder || "이름 찾기", "aria-label": o.placeholder || "찾기", autocomplete: "off"});
  const pg = pager({size: o.size || 10, row: o.row,
    empty: () => (st.items === undefined ? shimmer(3) : typeof o.empty === "function" ? o.empty() : empty(o.empty || "맞는 항목이 없습니다"))});
  const apply = (keep) => {
    const q = st.q.trim().toLowerCase(), items = st.items || [];
    pg.set(q ? items.filter((it) => o.match(it, q)) : items, keep);
  };
  input.addEventListener("input", () => { st.q = input.value; apply(false); });
  apply(false);
  return {el: h("div", {class: "stack tight"}, input, o.filters || null, pg.el),
    set(items, keep = true) { st.items = items || []; apply(keep); }, refresh: () => apply(true), input};
}

/** A small table (≤ ~30 rows; longer lists use pager). cols: [{label, l (left-aligned), get(row) -> text|Node}] */
export function table(cols, rows, onRow) {
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl"},
    h("thead", null, h("tr", null, cols.map((c) => h("th", {class: c.l ? "l" : ""}, c.label)))),
    h("tbody", null, rows.map((r) => h("tr", {class: onRow ? "click" : "", onclick: onRow ? () => onRow(r) : null},
      cols.map((c) => { const v = c.get(r); return h("td", {class: [c.l ? "l" : "", c.cls ? c.cls(r) : ""]}, v instanceof Node ? v : v ?? "—"); }))))));
}

// ---------------------------------------------------------------- charts: sparkline and thin curves
/** sparkline([v...], {w, h, cls: "ls"|"lc"|"lu"|"ld", base}) -> svg (values only; no axes). */
export function sparkline(values, o = {}) {
  const w = o.w || 120, hh = o.h || 36, vs = (values || []).filter((v) => v != null && Number.isFinite(v));
  if (vs.length < 2) return h("span", {class: "muted"}, "—");
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (o.base != null) { lo = Math.min(lo, o.base); hi = Math.max(hi, o.base); }
  const span = hi - lo || 1;
  const X = (i) => 1 + (w - 2) * i / (vs.length - 1), Y = (v) => hh - 1 - (hh - 2) * (v - lo) / span;
  const d = "M" + vs.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" L");
  return s("svg", {class: ["chart", "spark", o.cls2], viewBox: `0 0 ${w} ${hh}`, preserveAspectRatio: "none", role: "img", "aria-label": o.label || "흐름"},
    o.base != null ? s("line", {class: "base", x1: 0, x2: w, y1: Y(o.base), y2: Y(o.base)}) : null,
    s("path", {class: o.cls || (vs[vs.length - 1] >= vs[0] ? "lu" : "ld"), d}));
}

/**
 * curves({series: [{values, cls: "ls"|"lc", label}], base, yfmt, height, xlabels: [l, m, r], label}) -> div.curves
 * Thin lines (owners: "thin curves"), drawn at the box's real pixel width (crisp text on a phone and a PC; redrawn
 * when the box resizes). The values must be REAL (server series); with none it shows notYet() instead.
 */
export function curves(o) {
  const box = h("div", {class: "curves", style: {height: (o.height || 150) + "px"}});
  const all = o.series.flatMap((sr) => sr.values.filter((v) => v != null && Number.isFinite(v)));
  if (all.length < 2) { box.style.height = ""; box.append(notYet()); return box; }
  const draw = (W) => {
    const H = o.height || 150, x0 = 50, x1 = W - 10, y0 = 10, y1 = H - 22;
    const vals = [...all];
    if (o.base != null) vals.push(o.base);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.002 || 1;
    lo -= pad; hi += pad;
    const n = Math.max(...o.series.map((sr) => sr.values.length));
    const X = (i) => x0 + (x1 - x0) * i / Math.max(1, n - 1), Y = (v) => y1 - (y1 - y0) * (v - lo) / (hi - lo);
    const yf = o.yfmt || ((v) => num(v, 0));
    const kids = [];
    for (const v of [lo + pad, (lo + hi) / 2, hi - pad]) {
      kids.push(s("line", {class: "grid", x1: x0, x2: x1, y1: Y(v).toFixed(1), y2: Y(v).toFixed(1)}));
      kids.push(s("text", {class: "ax", x: x0 - 6, y: (Y(v) + 4).toFixed(1), "text-anchor": "end"}, yf(v)));
    }
    if (o.base != null) kids.push(s("line", {class: "base", x1: x0, x2: x1, y1: Y(o.base).toFixed(1), y2: Y(o.base).toFixed(1)}));
    for (const sr of o.series) {
      const pts = sr.values.map((v, i) => v == null ? null : `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).filter(Boolean);
      if (pts.length > 1) kids.push(s("path", {class: sr.cls || "ls", d: "M" + pts.join(" L")}));
      const last = sr.values.length - 1;
      if (last >= 0 && sr.values[last] != null) kids.push(s("circle", {class: sr.cls === "lc" ? "dc" : "ds", cx: X(last).toFixed(1), cy: Y(sr.values[last]).toFixed(1), r: 2.8}));
    }
    const xl = o.xlabels || [];
    if (xl[0]) kids.push(s("text", {class: "ax", x: x0, y: H - 4}, xl[0]));
    if (xl[1]) kids.push(s("text", {class: "ax", x: ((x0 + x1) / 2).toFixed(0), y: H - 4, "text-anchor": "middle"}, xl[1]));
    if (xl[2]) kids.push(s("text", {class: "ax", x: x1, y: H - 4, "text-anchor": "end"}, xl[2]));
    box.replaceChildren(s("svg", {class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": o.label || "곡선"}, kids));
  };
  let lastW = 0;
  const fit = () => { const w = Math.round(box.clientWidth); if (w > 60 && w !== lastW) { lastW = w; draw(w); } };
  if (typeof ResizeObserver === "function") new ResizeObserver(fit).observe(box);
  requestAnimationFrame(() => { fit(); if (!lastW) draw(320); });
  return box;
}

// ---------------------------------------------------------------- the green LED balance bar
/**
 * ledBar({label}) -> {el, update(d)}; d = {total, initialTotal, live: bool, curve: [v...]|null, stats: [text...],
 *   right: [{k, v (number), sign: true} | {k, text}], caption}. A `text` cell is words only (DeepSeek: counts, no money). Money counts to its new value when it changes (real data only).
 *   live: true only while the live stream is really connected.
 */
export function ledBar(o = {}) {
  const totalEl = h("b", {class: "num"}), pctEl = h("span", {class: "led-box num"}), absEl = h("span", {class: "num"});
  const liveEl = h("span", {class: "led-live off"}, "■ LIVE");
  const mid = h("div", {class: "led-m"});
  const right = h("div", {class: "led-r"});
  const cap = h("p", {class: "led-cap"});
  const el = h("section", {class: "ledbar", "aria-label": o.label || "모의 계좌 잔고"},
    h("div", null, h("div", {class: "led-k"}, h("span", {class: "t"}, o.label || "모의 계좌 잔고"), liveEl),
      h("div", {class: "led-n"}, totalEl, h("span", null, "USDT")), h("div", {class: "led-chg"}, pctEl, absEl)),
    mid, right, cap);
  const rightEls = new Map();
  el.update = (d) => {
    countTo(totalEl, d.total, {dec: 2, glow: true});          // glows teal / pink when the real total moved
    const ch = d.total != null && d.initialTotal ? d.total - d.initialTotal : null;
    countTo(pctEl, ch != null ? ch / d.initialTotal : null, {format: "pct", dec: 2, tone: true});
    countTo(absEl, ch, {dec: 2, sign: true, suffix: " USDT", tone: true});
    liveEl.classList.toggle("off", !d.live);
    liveEl.textContent = d.live ? "■ LIVE" : "■ 연결 끊김";
    clear(mid);
    if (d.curve && d.curve.length > 1) mid.append(sparkline(d.curve, {w: 300, h: 56, cls: "ln", base: d.initialTotal, label: "잔고 흐름"}));
    else if (d.curve === null) mid.append(h("div", {class: "led-stats"}, notYet("잔고 곡선 수집 전")));
    if (d.stats) mid.append(h("div", {class: "led-stats"}, d.stats.map((t) => h("span", null, t))));
    for (const r of d.right || []) {
      let cell = rightEls.get(r.k);
      if (!cell) {
        const v = h("b", {class: "num"});
        cell = {wrap: h("div", null, h("span", null, r.k), v), v};
        rightEls.set(r.k, cell); right.append(cell.wrap);
      }
      if (r.text != null) { cell.v.className = "led-txt"; cell.v.textContent = r.text; continue; }
      countTo(cell.v, r.v, {dec: 2, sign: r.sign !== false, tone: true});
    }
    cap.textContent = d.caption || ASSUME_KO;
  };
  return el;
}

// ---------------------------------------------------------------- small motion pieces (v4 additions, reusable)
/**
 * miniSpark(values, {w, h, base, refs: [{v, cls}], label, draw, tone}) -> a fixed-size svg for a list row or a card
 * (w x h px, default 60 x 20): the line, a dot at its end, an optional dashed base line (the start, an entry price)
 * and thin reference lines. The colour follows the end against the base (or the first value): up / down; tone
 * ("up" | "down") overrides it (a short position: price down = profit). draw: true draws it in once (motion.drawIn).
 * fluid: true fills its box's width (w is then only the drawing's aspect; no end dot, which would stretch).
 * Real values only; fewer than 2 gives an empty box of the same size (no layout jump while loading).
 */
export function miniSpark(values, o = {}) {
  const w = o.w || 60, hh = o.h || 20;
  const box = o.fluid ? {width: "100%", height: hh + "px", display: "block"}
    : {width: w + "px", height: hh + "px", display: "inline-block", verticalAlign: "middle", flex: "none"};
  const vs = (values || []).map((v) => (v == null || !Number.isFinite(Number(v)) ? null : Number(v)));
  const real = vs.filter((v) => v != null);
  if (real.length < 2) return s("svg", {class: ["chart", "mspark", "none"], viewBox: `0 0 ${w} ${hh}`, style: box, "aria-hidden": "true"});
  let lo = Math.min(...real), hi = Math.max(...real);
  const refs = (o.refs || []).filter((r) => r && Number.isFinite(Number(r.v)));
  for (const v of [o.base, ...refs.map((r) => r.v)]) if (v != null && Number.isFinite(Number(v))) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  const span = hi - lo || Math.abs(hi) * 0.001 || 1;
  const pad = 2.5;
  const X = (i) => pad + (w - 2 * pad) * i / Math.max(1, vs.length - 1);
  const Y = (v) => hh - pad - (hh - 2 * pad) * (v - lo) / span;
  let d = "", pen = false, lastI = 0;
  vs.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`; pen = true; lastI = i; });
  const ref = o.base != null ? o.base : real[0];
  const end = real[real.length - 1];
  const up = o.tone ? o.tone === "up" : end >= ref;
  const line = (v, cls) => s("line", {class: cls, x1: 0, x2: w, y1: Y(v).toFixed(1), y2: Y(v).toFixed(1)});
  const svg = s("svg", {class: ["chart", "mspark"], viewBox: `0 0 ${w} ${hh}`, style: box, role: "img", "aria-label": o.label || "흐름",
    preserveAspectRatio: o.fluid ? "none" : null},
    o.base != null ? line(o.base, "base") : null,
    refs.map((r) => line(Number(r.v), r.cls || "base")),
    s("path", {class: up ? "lu" : "ld", d}),
    o.fluid ? null : s("circle", {cx: X(lastI).toFixed(1), cy: Y(end).toFixed(1), r: 1.9, style: {fill: up ? "var(--up)" : "var(--down)"}}));
  if (o.draw) drawIn(svg);
  return svg;
}

/**
 * rankDelta(delta, {title, fade}) -> "▲2" / "▼1" (delta = earlier rank − rank now: positive = moved up), or null when
 * it did not move or there is nothing to compare with. Neutral glyph, meaning colours; fade: fade it in (a real change).
 */
export function rankDelta(delta, o = {}) {
  const n = Number(delta);
  if (!Number.isFinite(n) || n === 0) return null;
  const up = n > 0;
  const el = h("span", {class: ["rkd", up ? "up" : "down"], title: o.title || null,
    "aria-label": `순위 ${int(Math.abs(n))}칸 ${up ? "오름" : "내림"}`,
    style: {fontFamily: "var(--f-term)", fontSize: "var(--t-2xs)", fontWeight: "700", whiteSpace: "nowrap", lineHeight: "1"}},
  `${up ? "▲" : "▼"}${int(Math.abs(n))}`);
  if (o.fade) fadeIn(el);
  return el;
}

/**
 * rankMemo(key, {gapMs}) -> {base, save(values)} : a per-viewer "since your last visit" baseline (localStorage, a
 * convenience only: private windows simply show no arrows). values: {id: number} (e.g. each account's return now).
 * A visit is a run of saves less than gapMs apart (default 30 min); `base` is the last values of the visit before
 * this one ({ts, v} or null), so hopping between screens keeps the same arrows.
 */
export function rankMemo(key, o = {}) {
  const gap = o.gapMs || 30 * 60000;
  let st = local.get(key, null);
  if (!st || typeof st !== "object") st = {};
  const now = Date.now();
  if (st.cur && st.cur.seen && now - st.cur.seen > gap) { st.prev = {ts: st.cur.seen, v: st.cur.v}; st.cur = null; }
  const base = st.prev && st.prev.v && typeof st.prev.v === "object" ? st.prev : null;
  return {
    base,
    save(values) {
      const v = {};
      for (const [k, x] of Object.entries(values || {})) if (Number.isFinite(x)) v[k] = Math.round(x * 1e5) / 1e5;
      st.cur = {seen: Date.now(), v};
      local.set(key, st);
    },
  };
}
/** Ranks (1 = best) of ids by value, highest first: {id: rank}. */
export function ranksOf(values, ids) {
  const xs = (ids || Object.keys(values || {})).filter((k) => values && Number.isFinite(values[k]));
  xs.sort((a, b) => values[b] - values[a] || (a < b ? -1 : 1));
  return Object.fromEntries(xs.map((k, i) => [k, i + 1]));
}

// ---------------------------------------------------------------- toast
let toastT = null;
export function toast(text) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = text; t.classList.add("show");
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 4500);
}

export {$, $$};

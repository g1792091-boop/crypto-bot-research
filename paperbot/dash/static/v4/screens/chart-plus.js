// 차트 위 얹기 (chart-plus): three optional add-ons of the chart deck, all OFF until the viewer turns them on in the
// chart's '선' menu (remembered per device, core/dom.js local), shared by the terminal's chart and the 차트 screen:
//   시장 강제청산 거품   bubbles on the candles + price-bucket bars beside the price axis   (chart-liqmap.js)
//   우리 손절·청산 지도  our open positions' stops and liquidation prices beside the axis,
//                        hover: "이 가격이면 …"                                         (chart-stopmap.js)
//   아래 칸 (2개까지)    CVD · 미결제약정 · 펀딩 · 롱/숏 under the candles                 (chart-lower.js)
// Layout: the strips take their own column to the right of the price axis (the chart box gets narrower by exactly
// their width), so they never sit on the right-edge names or labels; the lower panes sit under the chart with the same
// right margin so the time axes line up. One slim note row per add-on under the chart says what it is and what it is not
// (market wide / only what our recorder heard / counts without money for DeepSeek and the coin flips): the honest label.
// The terminal's chart panel has a fixed height (the page is one screen): with ``minMain`` the panes only take what is
// left above that height (and hide the key line); a panel too low for even one says so in the menu instead of squeezing
// the candles. The 차트 screen's chart box has its own height, the panes simply add under it.
// Hooks into the screens: ONE call each after the deck exists (terminal-chart.js, chart.js); the deck's onData / menuEl /
// onToggle(…, how) (core/chartfx.js) are the only other touch points.
import {h, fmt, tok, features, bus} from "../core/pb.js";
import {liqMap} from "./chart-liqmap.js";
import {stopMap} from "./chart-stopmap.js";
import {lowerPanes, PANES} from "./chart-lower.js";
import {LIQ_TONE, minLiqUsd} from "./chart-plus-calc.js";
import {WORDS, readState, saveState, PANE_IDS} from "./chart-plus-kit.js";

const narrow = () => typeof matchMedia === "function" && matchMedia("(max-width: 599px)").matches;
const STRIP_W = {liq: 56, stops: 60};
const STRIP_W_PHONE = {liq: 38, stops: 46};
const PANE_H = {max: 88, min: 56};            // a pane's height: 56 px at the least, 88 px at the most (the terminal: 76, see fit())
const TERM_PANE_MAX = 76;

/**
 * chartPlus({ctx, deck, chart, series, wrap, box, key, sym, tf, minMain}) -> {state}
 *   key: "term" | "chart" (the per-device memory name), sym() / tf(): the coin and bar width on screen
 *   minMain: (px, the terminal) keep the candles at least this tall: the lower panes only get what is left
 */
export function chartPlus(o) {
  const {ctx, deck, chart, series, wrap} = o;
  const st = readState(o.key);
  // ---------------------------------------------------------------- the DOM: strips beside the axis, notes + panes under the chart
  const liqHost = h("div", {class: "cfxp-strip", dataset: {k: "liq"}, hidden: true});
  const stopHost = h("div", {class: "cfxp-strip", dataset: {k: "stops"}, hidden: true});
  const strips = h("div", {class: "cfxp-strips", hidden: true}, liqHost, stopHost);
  const notes = h("div", {class: "cfxp-notes"});
  const panesEl = h("div", {class: "cfxp-panes"});
  const below = h("div", {class: "cfxp-below", hidden: true}, notes, panesEl);
  wrap.append(strips);
  wrap.after(below);
  ctx.track(() => { strips.remove(); below.remove(); wrap.classList.remove("cfxp-has"); wrap.style.removeProperty("--cfxp-w"); if (below.parentElement) below.parentElement.classList.remove("cfxp-nokey"); });

  let cur = {sym: o.sym(), tf: o.tf()};           // the coin and bar width of the candles on screen (changes when the deck gets new candles)
  const symNow = () => cur.sym, tfNow = () => cur.tf;
  const views = {liq: {kind: "off"}, stops: {kind: "off"}, panes: []};
  let raf = 0, shown = [], room = {n: 2, h: PANE_H.max};
  function scheduleLayout() { if (!raf) raf = requestAnimationFrame(() => { raf = 0; layout(); }); }
  ctx.track(() => { if (raf) cancelAnimationFrame(raf); });

  // ---------------------------------------------------------------- the note rows (what is on, and what it is not)
  const dot = (side) => h("i", {class: ["cfxp-dot", side], dataset: {tone: LIQ_TONE[side]}, "aria-hidden": "true"});
  const openNotes = new Set();               // a phone shows two lines of a note; a tap opens the whole text (kept across refreshes)
  const say = (k, head, ...rest) => {
    const p = h("p", {class: ["cfxp-n", openNotes.has(k) ? "open" : ""], dataset: {k}}, h("b", null, head), " · ", ...rest);
    p.title = p.textContent;
    p.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      if (openNotes.has(k)) openNotes.delete(k); else openNotes.add(k);
      p.classList.toggle("open", openNotes.has(k));
    });
    return p;
  };
  function liqNote() {
    const v = views.liq;
    if (v.kind === "off") return null;
    const k = "시장 청산";
    if (v.kind === "unsupported") return say("liq", k, "월봉에서는 쓰지 않습니다");
    if (v.kind === "loading") return say("liq", k, "불러오는 중…");
    if (v.kind === "failed") return say("liq", k, "못 불러옴: 거품과 막대를 그리지 않았습니다 ", h("button", {type: "button", class: "cfxp-retry", onclick: () => L.reload()}, "다시 시도"));
    if (v.kind === "nofile") return say("liq", k, "기록기 자료가 없습니다 (서버에서 강제청산 기록기가 켜지면 보입니다)");
    const d = v.data || {}, since = d.since_ts ? `${fmt.kst(d.since_ts)}부터 ` : "";
    if (v.kind === "empty") return say("liq", k, `이 구간에 기록된 청산이 없습니다 (${since}기록기가 들은 것 기준 · 바이낸스 시장 전체, 우리 봇 아님)`);
    const parts = [`${WORDS.liq} · ${since}기록기가 들은 것만 · 코인마다 1초에 1건만 알려 줘서 실제보다 적음 · `, dot("long"), "롱 ", dot("short"), `숏 청산, 원 크기 = 금액 (BTC ${fmt.int(minLiqUsd("BTCUSDT") / 10000)}만 · 그 외 ${fmt.int(minLiqUsd("ETHUSDT") / 10000)}만 USDT부터 원으로, 작은 건 가격 막대에만)`];
    if (d.stale) parts.push(" · 기록기가 2시간 넘게 새 자료를 못 받음: 그 뒤는 모름");
    if ((d.gaps || []).length) parts.push(` · 빗금 = 기록이 끊겼던 때 (${fmt.int(d.gaps.length)}번)`);
    if (v.refreshFailed) parts.push(" · 새로 못 불러옴: 마지막 값");
    return say("liq", k, ...parts);
  }
  function stopNote() {
    const v = views.stops;
    if (v.kind === "off") return null;
    const k = "우리 손절·청산 지도";
    if (v.kind === "waiting") return say("stops", k, "불러오는 중…");
    if (v.kind === "none") return say("stops", k, "이 코인에 열린 포지션이 없습니다 (우리 모의 계좌 기준)");
    const bits = [`이 코인 열린 포지션 ${fmt.int(v.n)}개 · 손절선 ${fmt.int(v.stops)}개 · 청산가 ${fmt.int(v.liqs)}개 · 가격 막대에 마우스를 올리면 '이 가격이면'`];
    if (v.countOnly) bits.push(WORDS.countOnly(v.countOnly));
    bits.push(WORDS.stopsMath);
    return say("stops", k, bits.join(" · "));
  }
  function paneNote() {
    const bad = views.panes.filter((p) => !p.can || p.stale);
    const cut = st.panes.length - shown.length;
    if (!bad.length && cut <= 0) return null;
    const bits = bad.map((p) => `${PANES[p.id].ko}: ${p.stale ? "새로 못 받음 (마지막 값)" : p.failed ? "못 불러옴" : p.why || "그리지 못함"}`);
    if (cut > 0) bits.push(room.n ? `이 화면은 높이가 모자라 ${fmt.int(room.n)}개만 보입니다` : "이 화면은 높이가 모자라 아래 칸을 못 그립니다 (차트 화면에서는 보입니다)");
    return say("panes", "아래 칸", bits.join(" · "));
  }
  /** the terminal's chart panel cannot spare two or three note lines: with less than 44 px over the candles' minimum the notes
   *  become ONE line (each one's own words in order, the whole text in its tooltip) */
  function tight() {
    const pb = below.parentElement;
    if (!o.minMain || !pb) return false;
    let others = 0;
    for (const c of pb.children) if (c !== wrap && c !== below && !c.classList.contains("term-ckey") && c.offsetParent !== null) others += c.offsetHeight;
    return pb.clientHeight - others - o.minMain < 44;
  }
  function merged(rows) {
    const p = h("p", {class: "cfxp-n", dataset: {k: "all"}});
    rows.forEach((r, i) => { if (i) p.append(" ┃ "); p.append(...r.childNodes); });
    p.title = rows.map((r) => r.title).join("\n");
    return p;
  }
  let notesSig = "";
  function paintNotes() {
    let rows = [liqNote(), stopNote(), paneNote()].filter(Boolean);
    if (rows.length > 1 && tight()) rows = [merged(rows)];
    // rebuilt only when the words changed (the panes report every second: a hovered note's tooltip must not blink away)
    const sig = rows.map((r) => `${r.dataset.k}|${r.classList.contains("open")}|${r.title}`).join("\n");
    if (sig !== notesSig) { notesSig = sig; notes.replaceChildren(...rows); }
    notes.hidden = !rows.length;
    below.hidden = !rows.length && !shown.length;
    scheduleLayout();
  }

  // (the three parts report into the notes at once, so the note functions above are defined first)
  const L = liqMap({ctx, chart, series, wrap, deck, strip: liqHost, sym: symNow, tf: tfNow, report: (v) => { views.liq = v; paintNotes(); }});
  const S = stopMap({ctx, chart, series, wrap, deck, strip: stopHost, sym: symNow, report: (v) => { views.stops = v; paintNotes(); }});
  const P = lowerPanes({ctx, chart, series, deck, host: panesEl, sym: symNow, tf: tfNow, onClose: (id) => togglePane(id, false),
    report: (v) => { views.panes = v; paintNotes(); }});

  // ---------------------------------------------------------------- the strips' column, the chart box's width, the panes' room
  function fit() {
    const want = st.panes;
    if (!want.length) return {n: 0, h: PANE_H.max};
    const pb = below.parentElement;
    if (!o.minMain || !pb) return {n: Math.min(2, want.length), h: narrow() ? 84 : PANE_H.max};
    let others = 0;
    for (const c of pb.children) if (c !== wrap && c !== below && !c.classList.contains("term-ckey") && c.offsetParent !== null) others += c.offsetHeight;
    const budget = pb.clientHeight - others - o.minMain - notesH();
    const n = Math.max(0, Math.min(want.length, Math.floor(budget / PANE_H.min)));
    return {n, h: n ? Math.max(PANE_H.min, Math.min(TERM_PANE_MAX, Math.floor(budget / n))) : PANE_H.max, budget};
  }
  function layout() {
    const sw = narrow() ? STRIP_W_PHONE : STRIP_W, k = Math.max(1, (parseFloat(tok("--t-2xs")) || 12) / 12);     // 글자 크기 크게 / 아주 크게: wider strips
    // a phone has no room for two strips beside the axis: our own map keeps its strip, the market's price bars wait (the bubbles stay)
    const showLiq = st.liq && !(narrow() && st.stops);
    const wl = showLiq ? Math.round(sw.liq * k) : 0, ws = st.stops ? Math.round(sw.stops * k) : 0, w = wl + ws;
    liqHost.hidden = !showLiq; stopHost.hidden = !st.stops; strips.hidden = !w;
    liqHost.style.width = wl + "px"; stopHost.style.width = ws + "px";
    wrap.style.setProperty("--cfxp-w", w + "px");
    below.style.setProperty("--cfxp-w", w + "px");
    wrap.classList.toggle("cfxp-has", !!w);
    if (w) {
      let th = 0;
      try { th = chart.timeScale().height(); } catch (e) { /* mid-layout */ }
      strips.style.top = o.box.offsetTop + "px";
      strips.style.height = Math.max(0, o.box.clientHeight - th) + "px";
      L.paint(); S.paint();
    }
    // the lower panes: as many as fit (the newest choices), the terminal's key line gives its row up while they are on
    room = fit();
    const next = st.panes.slice(st.panes.length - room.n);
    if (next.join() !== shown.join()) {
      shown = next;
      P.set(shown);
      paintNotes();
    }
    panesEl.style.setProperty("--cfxp-ph", room.h + "px");
    if (below.parentElement && o.minMain) below.parentElement.classList.toggle("cfxp-nokey", !notes.hidden || !!shown.length);
    below.hidden = notes.hidden && !shown.length;
    menuPaint();
  }
  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => scheduleLayout());
    ro.observe(o.box);
    if (below.parentElement && o.minMain) ro.observe(below.parentElement);
    ctx.track(() => ro.disconnect());
  }
  chart.timeScale().subscribeVisibleLogicalRangeChange(() => { if (st.liq || st.stops) scheduleLayout(); });

  // ---------------------------------------------------------------- choices
  const save = () => saveState(o.key, st);
  function setLiq(on) { st.liq = on; save(); L.setOn(on); layoutNow(); }
  function setStops(on) { st.stops = on; save(); S.setOn(on); layoutNow(); }
  function togglePane(id, on) {
    const has = st.panes.includes(id);
    if (on && !has) {
      if (o.minMain && !fitsOne()) { ctx.toast("이 화면은 높이가 모자라 아래 칸을 켤 수 없습니다 · 차트 화면에서 켜 보세요"); return; }
      st.panes = [...st.panes, id].slice(-2);          // a third choice replaces the oldest
    } else if (!on && has) st.panes = st.panes.filter((x) => x !== id);
    save();
    layoutNow();
  }
  /** is there room for one more pane (the terminal: with the candles kept at minMain)? */
  function fitsOne() {
    const pb = below.parentElement;
    if (!pb) return true;
    let others = 0;
    for (const c of pb.children) if (c !== wrap && c !== below && !c.classList.contains("term-ckey") && c.offsetParent !== null) others += c.offsetHeight;
    return pb.clientHeight - others - o.minMain - notesH() >= PANE_H.min;
  }
  /** the height of the liquidation and stop-map notes (the line about panes that do not fit is not counted: it is the answer to this) */
  function notesH() {
    let t = 0;
    for (const c of notes.children) if (c.dataset.k !== "panes") t += c.offsetHeight;
    return t + (t ? 5 : 0);
  }
  function layoutNow() { paintNotes(); layout(); if (deck.place) deck.place(); }

  // ---------------------------------------------------------------- the '선' menu: a second column of its own
  const items = new Map();
  const item = (id, label, sub, on, fn) => {
    const b = h("button", {type: "button", class: "cfx-mi", role: "menuitemcheckbox", "aria-checked": String(on), onclick: fn},
      h("i", {class: "cfx-ck", "aria-hidden": "true"}), h("span", null, label), sub ? h("small", {class: "cfx-msub"}, sub) : null);
    items.set(id, b);
    return b;
  };
  const roomNote = h("p", {class: "cfx-mnote cfxp-roomnote", hidden: true}, "이 화면은 차트가 낮아서 아래 칸이 다 들어가지 않습니다. 차트 화면에서는 모두 보입니다.");
  const sec = h("div", {class: "cfxp-sec", role: "group", "aria-label": "차트에 더 얹기"},
    h("p", {class: "cfx-mhd"}, "겹쳐 보기 (처음엔 꺼 둠)"),
    item("liq", "시장 강제청산 거품", "바이낸스 전체", st.liq, () => setLiq(!st.liq)),
    item("stops", "우리 손절·청산 지도", "가격축 옆", st.stops, () => setStops(!st.stops)),
    h("p", {class: "cfx-mhd"}, "아래 칸 (동시에 2개까지)"),
    ...PANE_IDS.map((id) => item("p:" + id, PANES[id].ko, id === "cvd" ? "봉 자료로 계산" : "", st.panes.includes(id), () => togglePane(id, !st.panes.includes(id)))),
    roomNote,
    h("p", {class: "cfx-mnote"}, "이 기기에만 기억합니다. 시장 강제청산과 미결제약정·펀딩·롱/숏은 바이낸스 전체 시장 자료이고 우리 봇의 것이 아닙니다."));
  function menuPaint() {
    items.get("liq").setAttribute("aria-checked", String(st.liq));
    items.get("stops").setAttribute("aria-checked", String(st.stops));
    items.get("liq").hidden = features.probed && !features.liq && !st.liq;          // no liq.db on this server: the choice is not offered (CONTRACT 1.7)
    const noRoom = !!o.minMain && !st.panes.length && !fitsOne();
    for (const id of PANE_IDS) {
      const b = items.get("p:" + id);
      b.setAttribute("aria-checked", String(st.panes.includes(id)));
      b.setAttribute("aria-disabled", String(noRoom));
    }
    roomNote.hidden = !(noRoom || (!!o.minMain && st.panes.length > shown.length));       // saved panes that do not fit here are explained in the menu too
  }
  ctx.track(bus.on("features", () => menuPaint()));
  if (deck.menuEl) {
    deck.menuEl.classList.add("cfxp-two");
    deck.menuEl.append(sec);
  }
  // '기본으로' puts the calm chart back (all of this off); '모두 숨기기' too; '모두 보기' leaves the add-ons as they are
  deck.onToggle((g, how) => {
    if (g == null && (how === "default" || how === "none")) {
      if (st.liq) { st.liq = false; L.setOn(false); }
      if (st.stops) { st.stops = false; S.setOn(false); }
      st.panes = []; save();
      layoutNow();
    }
  });
  deck.onData((how) => {
    if (how === "set") cur = {sym: o.sym(), tf: o.tf()};
    L.onData(how); S.onData(how); P.onData(how);
    if (how === "set") scheduleLayout();
  });

  // ---------------------------------------------------------------- start from what this device chose
  if (st.liq) L.setOn(true);
  if (st.stops) S.setOn(true);
  ctx.every(20000, () => { if (st.liq) L.reload(); }, {now: false});
  paintNotes();
  scheduleLayout();
  return {state: st};
}

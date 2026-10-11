// 터미널 chart (the rule bot's v4 terminal-chart.js + chart-lines.js, copied and adapted to the 후보 리그): the candles of
// the chosen coin (1분 · 5분 · 15분 · 30분 · 1시간 · 4시간, Korea time; /api/klines, the dashboard server's cache of
// Binance's public bars — the browser never talks to Binance), the volume along the bottom, and the price tag on the
// right axis: the last price with the bar-close countdown under it (it glows once when the price really moved).
// Our positions: the SELECTED position's lines — 진입 (dashed), 손절 (red) or 잠금 (green: touching it closes in profit),
// 익절 (green, dashed) and 청산 추정 (dotted, "진입 때 기준" from the server's rebuild) — and a small chip at the left for
// up to five open positions of the chosen 묶음 on this coin ("롱 30배 +3.5%": live ROE at the mark price, before the exit
// fee); a chip picks that position. Marks: the selected account's entries ▲▼ and exits ● on this coin (/api/trades/<id>).
// The forming bar follows the page's 5 s live price; the last 50 bars are asked again every 15 s.
// D11: a hidden DeepSeek position gets no line, no chip and no marks (counted in the key line only). While the engine
// replays from 10/01 (or its record is old) the chips show no %: the positions are "그때 기준".
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as LK from "../lk.js";
import {loadLwc, color, tok} from "../chart.js";
import {liveRow, liveState, serverNow, markOf} from "../live.js";
import {livePnl, liveAllowed, inGroup} from "../poskit.js";
import {flashPrice} from "../v4kit.js";
import {coinShort, coinOf, sideKo, reasonKo, ROLE_SHORT} from "../labels.js";
import {panel, ping, mmss, TFS, TF_MS, TF_SHORT, hiddenPos, hiddenFill, pctOf} from "./terminal-kit.js";

const two = (x) => String(x).padStart(2, "0");
const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };
const MAX_CHIPS = 5;
const CHIP_H = 20;

/** termChart(ctx, st, hooks) -> {el, ready, setCoin(), setTf(), setSel(), onPositions(doc), onLive(), onBook(), tick(), dispose()}
 *  hooks: {onTf(tf), onPick(id), selPos() -> position|null, selAcct() -> account|null, book() -> {id, trades}|null} */
export function termChart(ctx, st, hooks) {
  const tfBtns = new Map();
  const tfBar = h("div", {class: "tm-tfs", role: "tablist", "aria-label": "봉"}, TFS.map((tf) => {
    const b = h("button", {type: "button", role: "tab", "aria-selected": String(tf === st.tf), title: `${TF_SHORT[tf]}봉`, onclick: () => hooks.onTf(tf)}, TF_SHORT[tf]);
    tfBtns.set(tf, b);
    return b;
  }));
  const legend = h("div", {class: "tm-legend num"});
  const box = h("div", {class: "tm-cbox", "aria-label": "캔들 차트 (한국 시각)"});
  const tag = h("div", {class: "tm-ptag", hidden: true, "aria-hidden": "true"}, h("b", {class: "num"}, "—"), h("small", {class: "num"}, "—"));
  const chips = h("div", {class: "tm-chips"});
  const msg = h("div", {class: "tm-cmsg", hidden: true, role: "status"});
  const wrap = h("div", {class: "tm-cwrap"}, box, legend, chips, tag, msg);
  const keyLine = h("div", {class: "tm-ckey"});
  const el = panel("차트", {cls: "tm-chart", acts: [tfBar, h("a", {class: "tm-more", href: "#/entries", title: "매매법마다 후보가 들어간 자리 (진입 차트 화면)"}, "진입 차트 →")]},
    wrap, keyLine);

  let C = null, candles = null, vol = null, ro = null, plines = [], first = null, lastBar = null, key = null, resetting = 0, endMode = false;
  let doc = null, focus = [];       // focus: the selected position's entry / stop / take-profit (kept inside the price scale)
  let failed = false;

  function showMsg(text) { msg.hidden = !text; msg.textContent = text || ""; }
  function paintLegend(d) {
    if (!d) { legend.textContent = ""; return; }
    const ch = d.open ? (d.close - d.open) / d.open : null;
    put(legend, h("b", null, `${coinShort(st.coin)} · ${TF_SHORT[st.tf]}`), ` 시 ${fmt.price(d.open)} 고 ${fmt.price(d.high)} 저 ${fmt.price(d.low)} 종 ${fmt.price(d.close)} `,
      h("span", {class: fmt.tone(ch, pctOf(ch, 2))}, pctOf(ch, 2)));
  }

  // ---------------------------------------------------------------- overlays: the price tag, the position chips
  function scaleBox() {
    try { return {sw: C.priceScale("right").width(), th: C.timeScale().height(), H: box.clientHeight - C.timeScale().height(), W: box.clientWidth}; }
    catch (e) { return null; }
  }
  function placeTag() {
    if (!candles || !lastBar) { tag.hidden = true; return; }
    const sb = scaleBox();
    const y = candles.priceToCoordinate(lastBar.close);
    if (!sb || y == null || y < 0 || y > sb.H) { tag.hidden = true; return; }
    tag.hidden = false;
    tag.style.transform = `translateY(${Math.round(y - 13)}px)`;
    tag.style.width = sb.sw + "px";
  }
  function paintTag(prev) {
    if (!lastBar) return;
    const up = lastBar.close >= lastBar.open;
    tag.classList.toggle("up", up); tag.classList.toggle("down", !up);
    tag.firstChild.textContent = fmt.price(lastBar.close);
    tag.lastChild.textContent = mmss(TF_MS[st.tf] - (serverNow() % TF_MS[st.tf]));
    if (prev != null && prev !== lastBar.close) flashPrice(tag, lastBar.close > prev ? "up" : "down");
    placeTag();
  }
  /** this coin's open positions of the chosen 묶음 that may show (not hidden): the selected one first, then by size of
   *  the unrealized P&L (when live numbers are allowed), else the newest */
  function coinPositions() {
    const all = (doc && !doc.status ? doc.positions || [] : []).filter((p) => p.coin === st.coin && inGroup(p, st.grp));
    const shown = all.filter((p) => !hiddenPos(p) && p.entry != null);
    const allowed = liveAllowed(doc);
    const score = (p) => { const u = allowed ? livePnl(p, markOf(p.coin)) : null; return u ? Math.abs(u.pnl) : -1; };
    shown.sort((a, b) => (b.id === st.sel) - (a.id === st.sel) || score(b) - score(a) || (b.since || 0) - (a.since || 0));
    return {all, shown, hidden: all.length - shown.length};
  }
  function placeChips() {
    if (!candles) { put(chips, null); return; }
    const sb = scaleBox();
    const {shown} = coinPositions();
    const allowed = liveAllowed(doc);
    const items = shown.slice(0, MAX_CHIPS).map((p) => {
      const u = allowed ? livePnl(p, markOf(p.coin)) : null;
      let y = candles.priceToCoordinate(Number(p.entry));
      let edge = "";
      if (!sb) return null;
      if (y == null || y < 2) { y = 2; edge = "↑ "; } else if (y > sb.H - CHIP_H) { y = sb.H - CHIP_H; edge = "↓ "; } else y -= CHIP_H / 2;
      return {p, u, y, edge};
    }).filter(Boolean).sort((a, b) => a.y - b.y);
    for (let i = 1; i < items.length; i++) if (items[i].y - items[i - 1].y < CHIP_H + 2) items[i].y = items[i - 1].y + CHIP_H + 2;
    put(chips, items.map((x) => {
      const on = x.p.id === st.sel;
      const roeTxt = x.u && x.u.roe != null ? pctOf(x.u.roe, 1) : "";
      return h("button", {type: "button", class: ["tm-chip", Number(x.p.side) > 0 ? "long" : "short", on ? "on" : "", x.u ? fmt.tone(x.u.pnl, roeTxt) : ""],
        style: {transform: `translateY(${Math.round(x.y)}px)`},
        title: `${LK.stratKo(x.p.name)} · ${ROLE_SHORT[x.p.role] || ""} · 진입 ${fmt.price(x.p.entry)}${x.edge ? " (차트 범위 밖)" : ""}${x.u ? " · ROE: 마크 가격 기준, 나갈 때 수수료 전" : ""} · 누르면 이 포지션의 선`,
        onclick: () => hooks.onPick(x.p.id)},
      x.edge, `${sideKo(x.p.side)} ${fmt.lev(x.p.lev)}`, roeTxt ? h("b", {class: "num"}, ` ${roeTxt}`) : null, h("small", null, ` ${ROLE_SHORT[x.p.role] || ""}`));
    }));
  }
  function paintKey() {
    const {all, shown, hidden} = coinPositions();
    const acct = hooks.selAcct();
    const sel = hooks.selPos();
    const hidSel = sel ? hiddenPos(sel) : acct ? LK.dsHidden(acct) : false;
    put(keyLine,
      h("span", null, h("i", {class: "k-ar"}), "진입 (롱 ▲ · 숏 ▼)"), h("span", null, h("i", {class: "k-up"}), "청산 이익"), h("span", null, h("i", {class: "k-dn"}), "청산 손실"),
      h("span", {title: "고른 포지션의 진입선 (점선) · 손절선 (빨강) 또는 잠금선 (초록: 닿으면 수익으로 끝남) · 익절선 · 청산 추정 (진입 때 기준)"},
        h("i", {class: "k-ln"}), "진입·손절·청산선"),
      h("span", {class: "tm-ckn"}, all.length ? `이 코인 ${fmt.int(all.length)}개 · 왼쪽 표시 ${fmt.int(Math.min(MAX_CHIPS, shown.length))}개${hidden ? ` · 딥시크 ${fmt.int(hidden)}개는 개수만` : ""}`
        : "고른 묶음은 이 코인에 열린 포지션 없음"),
      hidSel ? h("span", {class: "warn-t"}, "딥시크 금액 숨김: 이 계좌의 선과 거래 표시 없음") : null);
  }

  // ---------------------------------------------------------------- marks and lines
  const dsMoney = () => (doc && !doc.status ? !!doc.ds_money : !!(LK.league() && LK.league().ds_money));
  function decorate() {
    if (!candles) return;
    const acct = hooks.selAcct();
    const sel = hooks.selPos();
    const tfms = TF_MS[st.tf];
    const barT = (ms) => (Math.floor(Number(ms) / tfms) * tfms) / 1000;
    const inRange = (ms) => ms && first != null && Number(ms) / 1000 >= first;
    const marks = [];
    const cLong = color("--accent"), cShort = color("--warn", "--down"), cWin = color("--up"), cLoss = color("--down");
    const book = hooks.book();
    if (acct && book && book.id === acct.id) {
      for (const t of book.trades || []) {
        if (coinOf(t.symbol) !== st.coin || hiddenFill(t, acct, dsMoney())) continue;
        if (inRange(t.entry_time)) marks.push({time: barT(t.entry_time), position: t.side > 0 ? "belowBar" : "aboveBar", shape: t.side > 0 ? "arrowUp" : "arrowDown", color: t.side > 0 ? cLong : cShort, text: sideKo(t.side)});
        if (inRange(t.exit_time)) {
          const win = t.pnl != null ? t.pnl > 0 : !!t.win;
          marks.push({time: barT(Number(t.exit_time) - 1), position: t.side > 0 ? "aboveBar" : "belowBar", shape: "circle", color: win ? cWin : cLoss,
            text: `${reasonKo(t.exit_reason)}${t.roe == null ? "" : ` ${fmt.pct(t.roe * 100, true, 0)}`}`});
        }
      }
    }
    const o = sel && sel.coin === st.coin && !hiddenPos(sel) ? sel : null;
    if (o && inRange(o.since)) marks.push({time: barT(o.since), position: o.side > 0 ? "belowBar" : "aboveBar", shape: o.side > 0 ? "arrowUp" : "arrowDown", color: o.side > 0 ? cLong : cShort, text: `${sideKo(o.side)} 열림`});
    marks.sort((a, b) => a.time - b.time);
    try { candles.setMarkers(marks); } catch (e) { /* a mark outside the data */ }
    for (const p of plines) { try { candles.removePriceLine(p); } catch (e) { /* gone */ } }
    plines = [];
    focus = [];
    const line = (price, c, title, style, width = 1, axis = true) => {
      if (price == null || !Number.isFinite(Number(price))) return;
      plines.push(candles.createPriceLine({price: Number(price), color: c, lineWidth: width, lineStyle: style, axisLabelVisible: axis, title}));
    };
    // the other positions of this coin (the chips): a faint dotted entry line each
    for (const p of coinPositions().shown.slice(0, MAX_CHIPS)) if (!o || p.id !== o.id) line(p.entry, color("--line-2", "--muted"), "", 3, 1, false);
    if (o) {
      line(o.entry, color("--ink-2"), `진입 ${sideKo(o.side)} ${fmt.lev(o.lev)}`, 2, 1);
      if (o.stop != null) line(o.stop, o.stop_is_lock ? color("--up") : color("--down"), o.stop_is_lock ? "잠금" : "손절", 0, 2);
      if (o.tp != null) line(o.tp, color("--up"), "익절", 2, 1);
      if (o.liq != null) line(o.liq, color("--warn"), "청산 추정", 1, 1);
      focus = [o.entry, o.stop, o.tp].filter((x) => x != null).map(Number);
    }
    try { C.priceScale("right").applyOptions({autoScale: true}); } catch (e) { /* the scale is busy */ }
    const s = acct ? `${LK.stratKo(acct.name)} · ${TF_SHORT[acct.tf] || acct.tf} · ${ROLE_SHORT[acct.role] || ""}${o ? ` · ${sideKo(o.side)} 열림` : ""}` : "";
    el.sub.textContent = s;
    paintKey();
    placeChips();
  }

  // ---------------------------------------------------------------- data
  async function load(reset) {
    if (!candles) return;
    const coin = st.coin, tf = st.tf, at = st.at;
    const k = `${coin}|${tf}|${at || ""}`;
    if (k !== key) reset = true;
    if (!reset && (resetting || endMode)) return;
    let end = null;
    if (reset) {
      resetting += 1;
      key = k;
      // a past trade older than the newest 1000 bars: the bars around it (/api/klines end=, from 10/01 on)
      if (at && at < serverNow() - 900 * TF_MS[tf]) end = Math.round(at + 500 * TF_MS[tf]);
    }
    let d;
    try { d = await ctx.api(`/api/klines?coin=${coin}&tf=${tf}&limit=${reset ? 1000 : 50}${end ? `&end=${end}` : ""}`); }
    catch (e) {
      if (reset) resetting -= 1;
      if (e && e.name === "AbortError") return;
      if (reset && key === k) { failed = true; showMsg("차트 봉을 불러오지 못함 · 잠시 뒤 저절로 다시 받습니다"); }
      return;
    }
    if (reset) resetting -= 1;
    if (key !== k || !ctx.alive()) return;
    if (d.off) { showMsg("시세가 꺼져 있습니다 (CANDLEAGUE_DASH_LIVE=off)"); return; }
    const b = d.bars;
    if (!b || !b.t || !b.t.length) {
      showMsg(d.unavailable ? "바이낸스 연결 안 됨 · 잠시 뒤 다시 받습니다" : `${coinShort(coin)} 봉이 없습니다`);
      if (reset) { candles.setData([]); vol.setData([]); lastBar = null; first = null; tag.hidden = true; decorate(); }
      return;
    }
    failed = false;
    showMsg("");
    const upV = color("--vol-up", "--up"), dnV = color("--vol-down", "--down");
    const bar = (i) => ({time: b.t[i] / 1000, open: b.o[i], high: b.h[i], low: b.l[i], close: b.c[i]});
    const vbar = (i) => ({time: b.t[i] / 1000, value: b.v ? b.v[i] : 0, color: b.c[i] >= b.o[i] ? upV : dnV});
    const n = b.t.length;
    const prev = lastBar ? lastBar.close : null;
    if (reset) {
      endMode = !!end;
      const dec = priceDec(b.c[n - 1]);
      candles.applyOptions({priceFormat: {type: "price", precision: dec, minMove: Math.pow(10, -dec)}});
      candles.setData(b.t.map((_, i) => bar(i)));
      vol.setData(b.t.map((_, i) => vbar(i)));
      first = b.t[0] / 1000;
      lastBar = bar(n - 1);
      const narrow = box.clientWidth < 600;
      C.timeScale().setVisibleLogicalRange({from: Math.max(0, n - (narrow ? 90 : 170)), to: n + (narrow ? 4 : 8)});
    } else {
      for (let i = 0; i < n; i++) {
        if (!lastBar || b.t[i] / 1000 < lastBar.time) continue;
        candles.update(bar(i)); vol.update(vbar(i)); lastBar = bar(i);
      }
      if (lastBar && prev != null && lastBar.close !== prev) ping(el);
    }
    paintLegend(lastBar);
    paintTag(reset ? null : prev);
    decorate();
    if (reset && at) focusAt(at);
    requestAnimationFrame(() => { placeTag(); placeChips(); });
  }
  /** the chart scrolls to a past trade (its entry, and its exit when the selected account's record has it) */
  function focusAt(at) {
    if (first == null) return;
    const tfs = TF_MS[st.tf] / 1000;
    if (at / 1000 < first) { showMsg("이 거래는 차트 범위 밖입니다 (봉을 1시간 · 4시간으로 바꿔 보세요)"); return; }
    const book = hooks.book();
    const t = book && book.trades ? book.trades.find((x) => x.entry_time === at) : null;
    const from = Math.floor(at / 1000 / tfs) * tfs - 40 * tfs, to = Math.floor((t ? t.exit_time : at) / 1000 / tfs) * tfs + 40 * tfs;
    try { C.timeScale().setVisibleRange({from, to}); } catch (e) { /* out of range */ }
  }
  /** the page's live price moves the forming bar (only inside the bar on screen: a new bar comes with the next answer) */
  function liveTick() {
    if (!candles || !lastBar || endMode) return;
    const ls = liveState();
    if (!(ls.state === "ok" || ls.state === "fake")) return;
    const r = liveRow(st.coin);
    if (!r || r.ok === false || r.price == null) return;
    const p = Number(r.price), tfs = TF_MS[st.tf] / 1000;
    const barT = Math.floor(serverNow() / 1000 / tfs) * tfs;
    if (barT > lastBar.time) { load(false); return; }
    if (barT !== lastBar.time) return;
    const prev = lastBar.close;
    const c = {...lastBar, close: p, high: Math.max(lastBar.high, p), low: Math.min(lastBar.low, p)};
    try { candles.update(c); } catch (e) { return; }
    lastBar = c;
    paintLegend(lastBar); paintTag(prev);
  }

  // ---------------------------------------------------------------- the chart itself
  const ready = (async () => {
    let L;
    try { L = await loadLwc(); } catch (e) { showMsg("차트 파일을 불러오지 못했습니다 (새로 고침해 보세요)"); return; }
    if (!ctx.alive()) return;
    const kstTick = (t, type) => {
      const d = new Date(t * 1000 + 9 * 3.6e6);
      if (type === 0) return String(d.getUTCFullYear());
      if (type === 1) return `${d.getUTCMonth() + 1}월`;
      if (type === 2) return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
      return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
    };
    C = L.createChart(box, {width: box.clientWidth || 600, height: box.clientHeight || 360,
      layout: {background: {color: tok("--surface")}, textColor: tok("--ink-2"), fontSize: 12, fontFamily: tok("--f-term") || tok("--f-body")},
      grid: {vertLines: {color: tok("--line")}, horzLines: {color: tok("--line")}},
      rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.08, bottom: 0.2}},
      timeScale: {borderColor: tok("--line-2"), timeVisible: true, secondsVisible: false, rightOffset: 8, tickMarkFormatter: kstTick},
      crosshair: {mode: 0},
      localization: {locale: "ko-KR", priceFormatter: (p) => fmt.price(p),
        timeFormatter: (t) => { const d = new Date(t * 1000 + 9 * 3.6e6); return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${two(d.getUTCHours())}:${two(d.getUTCMinutes())} KST`; }},
      handleScroll: {vertTouchDrag: false}, handleScale: {axisPressedMouseMove: {time: true, price: true}}});
    const up = color("--up"), down = color("--down");
    candles = C.addCandlestickSeries({upColor: up, downColor: down, borderVisible: false, wickUpColor: up, wickDownColor: down,
      lastValueVisible: false, priceLineVisible: true, priceLineStyle: 2, priceLineWidth: 1, priceLineColor: color("--accent"),
      // the selected position's entry / stop / take-profit stay inside the price scale (never the liquidation line)
      autoscaleInfoProvider: (orig) => {
        const r = orig();
        if (!r || !r.priceRange || !focus.length) return r;
        return {...r, priceRange: {minValue: Math.min(r.priceRange.minValue, ...focus), maxValue: Math.max(r.priceRange.maxValue, ...focus)}};
      }});
    vol = C.addHistogramSeries({priceFormat: {type: "volume"}, priceScaleId: "", lastValueVisible: false, priceLineVisible: false});
    C.priceScale("").applyOptions({scaleMargins: {top: 0.84, bottom: 0}});
    C.subscribeCrosshairMove((p) => { const d = p && p.seriesData && p.seriesData.get(candles); paintLegend(d || lastBar); });
    C.timeScale().subscribeVisibleLogicalRangeChange(() => requestAnimationFrame(() => { placeTag(); placeChips(); }));
    if (typeof ResizeObserver === "function") {
      ro = new ResizeObserver(() => { if (!C) return; C.resize(box.clientWidth, box.clientHeight); requestAnimationFrame(() => { placeTag(); placeChips(); }); });
      ro.observe(box);
    }
    await load(true);
  })();

  ctx.every(15000, () => load(false));
  ctx.every(30000, () => { if (failed) load(true); });
  return {
    el, ready,
    setCoin() { load(true); },
    setTf(tf) { for (const [k, b] of tfBtns) b.setAttribute("aria-selected", String(k === tf)); load(true); },
    setSel() { decorate(); },
    onPositions(d) { doc = d; decorate(); },
    onLive() { liveTick(); placeChips(); },
    onBook() { decorate(); if (st.at && first != null) focusAt(st.at); },
    tick() { if (lastBar) { tag.lastChild.textContent = mmss(TF_MS[st.tf] - (serverNow() % TF_MS[st.tf])); } },
    reload() { load(true); },
    dispose() { if (ro) ro.disconnect(); try { if (C) C.remove(); } catch (e) { /* gone */ } C = null; candles = null; },
  };
}

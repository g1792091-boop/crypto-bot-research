// 터미널 chart (the rule bot's v4 terminal-chart.js + chart-lines.js, copied and adapted to the 후보 리그): the candles of
// the chosen coin (1분 · 5분 · 15분 · 30분 · 1시간 · 4시간, Korea time; /api/klines, the dashboard server's cache of
// Binance's public bars — the browser never talks to Binance), the volume along the bottom, and the price tag on the
// right axis: the last price with the bar-close countdown under it (it glows once when the price really moved).
// Our positions: the SELECTED position's lines — 진입 (dashed), 손절 (red) or 잠금 (green: touching it closes in profit),
// 익절 (green, dashed) and 청산 추정 (dotted, "진입 때 기준" from the server's rebuild) — and a small chip at the left for
// up to five open positions of the chosen 묶음 on this coin ("롱 30배 +3.5%": live ROE at the mark price, before the exit
// fee); a chip picks that position. Marks: the selected account's entries ▲▼ and exits ● on this coin (/api/trades/<id>).
// The forming bar follows the page's 5 s live price; the last 50 bars are asked again every 15 s. The price scale keeps
// the selected position's entry in view, and its stop / take-profit only while they lie near the bars on screen (within
// one more bar range above or below): a 3R take-profit 10 % away would squeeze the candles into a thin band, so a line
// that far is left off the scale and named at the chart's edge instead ("익절 73,014.5 ↓ −11.6% · 차트 밖").
// D11: a hidden DeepSeek position gets no line, no chip and no marks (counted in the key line only). While the engine
// replays from 10/01 (or its record is old) the chips show no %: the positions are "그때 기준".
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as LK from "../lk.js";
import {loadLwc, color, tok} from "../chart.js";
import {liveRow, liveState, serverNow, markOf} from "../live.js";
import {livePnl, liveOk, inGroup} from "../poskit.js";
import {flashPrice} from "../v4kit.js";
import {coinShort, coinOf, sideKo, reasonKo, ROLE_SHORT} from "../labels.js";
import {panel, ping, mmss, TFS, TF_MS, TF_SHORT, hiddenPos, hiddenFill, pctOf} from "./terminal-kit.js";

const two = (x) => String(x).padStart(2, "0");
const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };
const MAX_CHIPS = 5;
const NEAR = 0.0005;                    // entries this close share one chip (the rule bot's chart-lines.js)
const CHIP_H = 20;

/** Whether a line of the selected position stays inside the price scale: the entry always; a stop or take-profit while
 *  it lies within one more bar range (at least 0.2 % of the price) above or below the visible bars, so the candles keep
 *  at least about a third of the chart's height. */
export function inBand(f, b) {
  if (!f || f.keep || !b) return true;
  const room = Math.max(b.hi - b.lo, Math.abs(b.hi) * 0.002);
  return f.v >= b.lo - room && f.v <= b.hi + room;
}

/** termChart(ctx, st, hooks) -> {el, ready, setCoin(), setTf(), setSel(), onPositions(doc), onLive(), onBook(), tick(), dispose()}
 *  hooks: {onTf(tf), onPick(id), selPos() -> position|null, selAcct() -> account|null, book() -> {id, trades}|null} */
export function termChart(ctx, st, hooks) {
  const tfBtns = new Map();
  const tfBar = h("div", {class: "tm-tfs", role: "tablist", "aria-label": "봉"}, TFS.map((tf) => {
    const b = h("button", {type: "button", role: "tab", "aria-selected": String(tf === st.tf), title: `${TF_SHORT[tf]}봉`,
      onclick: () => { if (tf === st.tf && endMode) { st.at = null; load(true); } else hooks.onTf(tf); }}, TF_SHORT[tf]);
    tfBtns.set(tf, b);
    return b;
  }));
  const legend = h("div", {class: "tm-legend num"});
  const box = h("div", {class: "tm-cbox", "aria-label": "캔들 차트 (한국 시각)"});
  const tag = h("div", {class: "tm-ptag", hidden: true, "aria-hidden": "true"}, h("b", {class: "num"}, "—"), h("small", {class: "num"}, "—"));
  const chips = h("div", {class: "tm-chips"});
  const msg = h("div", {class: "tm-cmsg", hidden: true, role: "status"});
  const edgeUp = h("span", {class: "tm-cedge up", hidden: true}), edgeDn = h("span", {class: "tm-cedge dn", hidden: true});
  const wrap = h("div", {class: "tm-cwrap"}, box, legend, chips, tag, edgeUp, edgeDn, msg);
  const keyLine = h("div", {class: "tm-ckey"});
  const el = panel("차트", {cls: "tm-chart", acts: [tfBar, h("a", {class: "tm-more", href: "#/entries", title: "매매법마다 후보가 들어간 자리 (진입 차트 화면)"}, "진입 차트 →")]},
    wrap, keyLine);

  let C = null, candles = null, vol = null, ro = null, plines = [], first = null, lastBar = null, key = null, resetting = 0, endMode = false;
  let doc = null, focus = [];       // focus: the selected position's entry / stop / take-profit [{v, ko, keep}]
  let bars = null;                   // the visible bars' own price range at the last autoscale {lo, hi}
  let failed = false;
  const chipEls = new Map();         // group of position ids -> its chip button (kept across repaints)

  function showMsg(text) { msg.hidden = !text; msg.textContent = text || ""; }
  function paintLegend(d) {
    if (!d) { legend.textContent = ""; return; }
    const ch = d.open ? (d.close - d.open) / d.open : null;
    put(legend, h("b", null, `${coinShort(st.coin)} · ${TF_SHORT[st.tf]}`), ` 시 ${fmt.price(d.open)} 고 ${fmt.price(d.high)} 저 ${fmt.price(d.low)} 종 ${fmt.price(d.close)} `,
      h("span", {class: fmt.tone(ch, pctOf(ch, 2))}, pctOf(ch, 2)),
      endMode ? h("span", {class: "warn-t"}, " · 지난 거래 둘레의 봉 (지금 봉은 봉 단추를 다시 누르면)") : null);
  }

  // ---------------------------------------------------------------- overlays: the price tag, the position chips
  function scaleBox() {
    try { return {sw: C.priceScale("right").width(), th: C.timeScale().height(), H: box.clientHeight - C.timeScale().height(), W: box.clientWidth}; }
    catch (e) { return null; }
  }
  function placeTag() {
    if (!candles || !lastBar || endMode) { tag.hidden = true; return; }
    const sb = scaleBox();
    const y = candles.priceToCoordinate(lastBar.close);
    if (!sb || y == null || y < 0 || y > sb.H) { tag.hidden = true; return; }
    tag.hidden = false;
    tag.style.transform = `translateY(${Math.round(y - 13 + (box.offsetTop || 0))}px)`;
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
    const allowed = liveOk(doc);
    const score = (p) => { const u = allowed ? livePnl(p, markOf(p.coin)) : null; return u ? Math.abs(u.pnl) : -1; };
    shown.sort((a, b) => (b.id === st.sel) - (a.id === st.sel) || score(b) - score(a) || (b.since || 0) - (a.since || 0));
    return {all, shown, hidden: all.length - shown.length};
  }
  /** the chips: positions of one side within 0.05 % of each other share one chip ("숏 20배 ×2 +11.0%": the group's
   *  P&L over its margin); the five groups that matter most (the selected one first) */
  function chipGroups() {
    const allowed = liveOk(doc);
    const groups = [];
    for (const p of coinPositions().shown) {
      const e = Number(p.entry);
      const g = groups.find((x) => x.side === Number(p.side) && Math.abs(e - x.price) / x.price < NEAR);
      if (g) g.items.push(p); else groups.push({side: Number(p.side), price: e, items: [p]});
    }
    for (const g of groups) {
      let pnl = 0, mg = 0, known = 0;
      for (const p of g.items) {
        const u = allowed ? livePnl(p, markOf(p.coin)) : null;
        if (u) { pnl += u.pnl; mg += Number(p.margin) || 0; known += 1; }
      }
      g.pnl = known === g.items.length && known ? pnl : null;
      g.roe = g.pnl != null && mg > 0 ? pnl / mg : null;
      g.on = g.items.some((p) => p.id === st.sel);
    }
    return groups.slice(0, MAX_CHIPS);
  }
  function placeChips() {
    if (!candles) { put(chips, null); return; }
    const sb = scaleBox();
    if (!sb) return;
    paintEdge(sb);
    const oy = box.offsetTop || 0;                // a phone: the legend has its own line above the chart
    const TOP = oy ? oy + 2 : 26;                 // under the legend line
    const items = chipGroups().map((g) => {
      const c = candles.priceToCoordinate(g.price);
      const raw = c == null ? null : c + oy;
      let y, edge = "";
      if (raw == null) y = TOP;                                   // (no bars yet)
      else if (raw < TOP) { y = TOP; edge = "↑ "; }               // above what the chart shows
      else if (raw > oy + sb.H - CHIP_H / 2) { y = oy + sb.H - CHIP_H; edge = "↓ "; }
      else y = Math.max(TOP, raw - CHIP_H / 2);
      return {g, y, edge};
    }).sort((a, b) => a.y - b.y);
    for (let i = 1; i < items.length; i++) if (items[i].y - items[i - 1].y < CHIP_H + 2) items[i].y = items[i - 1].y + CHIP_H + 2;
    // a chip that stays (same positions) is updated in place, so a hover or a click is never lost to the 5 s repaint
    const keep = new Set();
    const nodes = items.map(({g, y, edge}) => {
      const first = g.items[0], n = g.items.length;
      const gid = g.items.map((p) => p.id).sort().join(",");
      keep.add(gid);
      const levs = new Set(g.items.map((p) => p.lev));
      const roeTxt = g.roe != null ? pctOf(g.roe, 1) : "";
      const names = g.items.slice(0, 4).map((p) => `${LK.stratKo(p.name)} (${ROLE_SHORT[p.role] || ""})`).join(", ") + (n > 4 ? ` 외 ${n - 4}개` : "");
      let b = chipEls.get(gid);
      if (!b) {
        b = h("button", {type: "button", onclick: () => hooks.onPick(b._on ? st.sel : b._first)});
        chipEls.set(gid, b);
      }
      b._on = g.on; b._first = first.id;
      b.className = ["tm-chip", g.side > 0 ? "long" : "short", g.on ? "on" : "", g.pnl != null ? fmt.tone(g.pnl, roeTxt) : ""].filter(Boolean).join(" ");
      b.style.transform = `translateY(${Math.round(y)}px)`;
      b.title = `진입 ${fmt.price(g.price)} · ${names}${edge ? " · 차트 범위 밖" : ""}${roeTxt ? " · ROE: 마크 가격 기준, 나갈 때 수수료 전" : ""} · 누르면 이 포지션의 선`;
      put(b, edge, `${sideKo(g.side)}${levs.size === 1 ? ` ${fmt.lev(first.lev)}` : ""}${n > 1 ? ` ×${n}` : ""}`, roeTxt ? h("b", {class: "num"}, ` ${roeTxt}`) : null,
        n === 1 ? h("small", null, ` ${ROLE_SHORT[first.role] || ""}`) : null);
      return b;
    });
    for (const k of [...chipEls.keys()]) if (!keep.has(k)) chipEls.delete(k);
    const same = nodes.length === chips.childNodes.length && nodes.every((x, i) => chips.childNodes[i] === x);
    if (!same) put(chips, nodes);
  }
  /** The selected position's lines left off the price scale (too far from the bars on screen): named at the top or
   *  the bottom edge of the chart with their distance from the price now. */
  function paintEdge(sb) {
    const off = bars ? focus.filter((f) => !inBand(f, bars)) : [];
    const ref = lastBar ? lastBar.close : null;
    const txt = (f) => `${f.ko} ${fmt.price(f.v)}${ref ? ` ${f.v > ref ? "↑" : "↓"} ${pctOf((f.v - ref) / ref, 1)}` : ""}`;
    const ups = off.filter((f) => ref == null || f.v > ref), dns = off.filter((f) => ref != null && f.v <= ref);
    const right = sb ? `${sb.sw + 6}px` : "70px";
    for (const [node, xs, y] of [[edgeUp, ups, (box.offsetTop || 0) + (box.offsetTop ? 4 : 28)], [edgeDn, dns, null]]) {
      node.hidden = !xs.length;
      node.textContent = xs.length ? `${xs.map(txt).join(" · ")} · 차트 밖` : "";
      node.style.right = right;
      if (y != null) node.style.top = `${y}px`;
      else if (sb) node.style.top = `${Math.round((box.offsetTop || 0) + sb.H * 0.84 - 22)}px`;
    }
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
      h("span", {class: "tm-ckn"}, all.length ? `이 코인 ${fmt.int(all.length)}개 · 왼쪽 표시 ${fmt.int(shown.length ? chipGroups().reduce((n, g) => n + g.items.length, 0) : 0)}개${hidden ? ` · 딥시크 ${fmt.int(hidden)}개는 개수만` : ""}`
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
    if (o && inRange(o.since)) marks.push({time: barT(o.since), position: o.side > 0 ? "belowBar" : "aboveBar", shape: o.side > 0 ? "arrowUp" : "arrowDown", color: o.side > 0 ? cLong : cShort, text: sideKo(o.side)});
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
    for (const g of chipGroups()) if (!o || !g.items.some((p) => p.id === o.id)) line(g.price, color("--line-2", "--muted"), "", 3, 1, false);
    if (o) {
      line(o.entry, color("--ink-2"), `진입 ${sideKo(o.side)} ${fmt.lev(o.lev)}`, 2, 1);
      if (o.stop != null) line(o.stop, o.stop_is_lock ? color("--up") : color("--down"), o.stop_is_lock ? "잠금" : "손절", 0, 2);
      if (o.tp != null) line(o.tp, color("--up"), "익절", 2, 1);
      if (o.liq != null) line(o.liq, color("--warn"), "청산 추정", 1, 1);
      focus = [{v: o.entry, ko: "진입", keep: true}, {v: o.stop, ko: o.stop_is_lock ? "잠금" : "손절"}, {v: o.tp, ko: "익절"}]
        .filter((f) => f.v != null && Number.isFinite(Number(f.v))).map((f) => ({...f, v: Number(f.v)}));
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
      // the selected position's entry stays inside the price scale, its stop / take-profit only while near the bars on
      // screen (inBand); never the liquidation line. The bars' own range is kept for the edge labels (paintEdge).
      autoscaleInfoProvider: (orig) => {
        const r = orig();
        if (!r || !r.priceRange) return r;
        bars = {lo: r.priceRange.minValue, hi: r.priceRange.maxValue};
        const vs = focus.filter((f) => inBand(f, bars)).map((f) => f.v);
        if (!vs.length) return r;
        return {...r, priceRange: {minValue: Math.min(r.priceRange.minValue, ...vs), maxValue: Math.max(r.priceRange.maxValue, ...vs)}};
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

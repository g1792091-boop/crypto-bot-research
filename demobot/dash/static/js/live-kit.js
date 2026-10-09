// Round 4 part A kit (demobot/CONTRACT.md 9.1-9.4, 9.9): what 터미널 · 포지션 · 여러 차트 · 시장 · 신호 · 데이터 점검 ·
// 타임라인 share. The candle chart with our open positions as price lines and recent trades as marks (the vendored
// lightweight-charts, same as chart.js), small SVG sparklines, the long / short vote bar, the sortable table, the
// trade-chart link of a position, the live P&L of a position at the live price, and the screens' own stylesheet
// (/static/live.css, loaded once on first use like the rule bot's v4 router does). Text is always text (dom.js h()).
import {h, s, put} from "./dom.js";
import * as fmt from "./fmt.js";
import {loadLwc, tok, color} from "./chart.js";
import {sideKo, targetR} from "./labels.js";

// ---------------------------------------------------------------- the stylesheet (once)
let cssP = null;
export function needCss() {
  if (cssP) return cssP;
  cssP = new Promise((ok) => {
    if (document.querySelector('link[data-live-css]')) { ok(); return; }
    const l = document.createElement("link");
    l.rel = "stylesheet"; l.href = "/static/live.css"; l.dataset.liveCss = "1";
    l.onload = () => ok(); l.onerror = () => { cssP = null; l.remove(); ok(); };   // the page still works unstyled
    document.head.appendChild(l);
  });
  return cssP;
}

// ---------------------------------------------------------------- words and numbers
export const TFS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];
export const TF_SHORT = {"1m": "1분", "5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일"};
export const TF_MS = {"1m": 60000, "5m": 300000, "15m": 900000, "30m": 1800000, "1h": 3600000, "4h": 14400000, "1d": 86400000};
export const STRATS = ["S2_ST_ROC", "N02_ST_KST", "N04_ST_KLINGER"];
export const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };
export const px = (p) => (fmt.bad(p) ? "—" : fmt.num(p, priceDec(p)));
/** Big money in Korean units: 1.2조 / 12.3억 / 4,500만 / 9,800 (USD). */
export function usdKo(x) {
  if (fmt.bad(x)) return "—";
  const v = Number(x), a = Math.abs(v);
  if (a >= 1e12) return `${fmt.num(v / 1e12, 2)}조`;
  if (a >= 1e8) return `${fmt.num(v / 1e8, a >= 1e10 ? 0 : 1)}억`;
  if (a >= 1e4) return `${fmt.num(v / 1e4, 0)}만`;
  return fmt.num(v, 0);
}
/** "1.2K" / "−7.5K" / "356" for calendar cells and axis labels. */
export function shortNum(v) {
  if (fmt.bad(v)) return "—";
  const a = Math.abs(Number(v));
  return a >= 1e6 ? `${fmt.num(v / 1e6, 1, true)}M` : a >= 1e4 ? `${fmt.num(v / 1e3, 0, true)}K` : a >= 1e3 ? `${fmt.num(v / 1e3, 1, true)}K` : fmt.num(v, 0, true);
}
/** Funding per 8 h as a percent with 4 decimals: 0.0001 -> "+0.0100%". */
export const fundPct = (r) => (fmt.bad(r) ? "—" : `${fmt.num(Number(r) * 100, 4, true)}%`);
/** mm:ss or h:mm:ss until a time (negative: "지금"). */
export function countdown(ms, now = Date.now()) {
  if (fmt.bad(ms)) return "—";
  let t = Math.floor((Number(ms) - now) / 1000);
  if (t <= 0) return "곧";
  const two = (x) => String(x).padStart(2, "0");
  const hh = Math.floor(t / 3600); t -= hh * 3600;
  return hh ? `${hh}:${two(Math.floor(t / 60))}:${two(t % 60)}` : `${two(Math.floor(t / 60))}:${two(t % 60)}`;
}
/** A short age "6초" / "4분" / "2시간" / "3일". */
export function age(ms, now = Date.now()) {
  const sec = Math.max(0, Math.floor((now - Number(ms)) / 1000));
  if (!Number.isFinite(sec)) return "—";
  return sec < 60 ? `${sec}초` : sec < 3600 ? `${Math.floor(sec / 60)}분` : sec < 86400 ? `${Math.floor(sec / 3600)}시간` : `${Math.floor(sec / 86400)}일`;
}
export const sideTag = (side) => h("span", {class: ["side", Number(side) > 0 ? "long" : "short"]}, sideKo(side));

// ---------------------------------------------------------------- positions
/** The trade key of a position (positions.json has no key): coin|tf|signal bar|side|L, the signal bar being the bar
 *  before the entry (CONTRACT 1: entry at the close of the signal bar). trade.js also finds the trade by its entry
 *  time (?at=) when a key does not match. */
export function tradeKey(p) {
  const step = TF_MS[p.tf] || TF_MS["15m"];
  return `${p.coin}|${p.tf}|${Number(p.entry_ms) - step}|${Number(p.side) > 0 ? 1 : -1}|${p.L}`;
}
export function tradeHref(ctx, p, from) {
  return ctx.href("trade", p.id, {at: String(p.entry_ms), from}, p.key || tradeKey(p));
}
/** The P&L of a position at a newer price: the snapshot's own number (fees in) plus the move since its "last". */
export function liveUnreal(p, price) {
  const u = Number(p.unreal);
  if (fmt.bad(price) || fmt.bad(p.last) || fmt.bad(p.entry) || !Number(p.entry)) return Number.isFinite(u) ? u : null;
  return u + Number(p.side) * (Number(price) - Number(p.last)) / Number(p.entry) * Number(p.notional || 0);
}
/** "20~50배" / "20·30배" / "40배". */
export function levText(Ls) {
  const xs = [...new Set(Ls.map(Number))].sort((a, b) => a - b);
  if (!xs.length) return "—";
  if (xs.length === 4 && xs[0] === 20 && xs[3] === 50) return "20~50배";
  return `${xs.join("·")}배`;
}
/** One entry per account (its leverage lines share the entry and the stop): {id, name, kind, coin, side, tf, entry,
 *  stop, target, entry_ms, Ls, unreal (sum), notional (sum), stop_dist_pct, R (20x line or first), rows}. */
export function groupEntries(rows) {
  const m = new Map();
  for (const p of rows || []) {
    const k = `${p.id}|${p.coin}|${p.entry_ms}|${p.side}`;
    let g = m.get(k);
    if (!g) {
      g = {id: p.id, name: p.name, kind: p.kind, coin: p.coin, side: Number(p.side), tf: p.tf, entry: p.entry, stop: p.stop,
        target: p.target, entry_ms: p.entry_ms, last: p.last, stop_dist_pct: p.stop_dist_pct, setting_ko: p.setting_ko,
        exit_ko: p.exit_ko, Ls: [], rows: [], unreal: 0, R: p.R, first: p};
      m.set(k, g);
    }
    g.Ls.push(Number(p.L)); g.rows.push(p);
    g.unreal += Number(p.unreal) || 0;
    if (Number(p.L) === 20) { g.R = p.R; g.first = p; }
  }
  return [...m.values()].sort((a, b) => b.entry_ms - a.entry_ms);
}
/** The distance from a price to the stop, as the adverse move in percent ("−1.2%"). */
export function stopText(g, price) {
  const p = !fmt.bad(price) ? Number(price) : Number(g.last);
  const d = !fmt.bad(g.stop) && p ? Math.abs(p - Number(g.stop)) / p * 100 : Number(g.stop_dist_pct);
  return fmt.bad(d) ? "—" : `−${fmt.num(d, d < 1 ? 2 : 1)}%`;
}

// ---------------------------------------------------------------- small SVG pieces
/** spark(points [[t, v], ...] or [v...], {w, h, cls, zero, area, dots}) -> <svg>: a sparkline that scales to its box. */
export function spark(points, o = {}) {
  const W = o.w || 120, H = o.h || 28, pad = 2;
  const vals = (points || []).map((p) => (Array.isArray(p) ? Number(p[o.col || 1]) : Number(p))).filter(Number.isFinite);
  const svg = s("svg", {class: ["lv-spark", o.cls], viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
    "aria-label": o.label || "작은 선 그래프"});
  if (vals.length < 2) { svg.append(s("line", {class: "lv-sp-none", x1: 0, x2: W, y1: H / 2, y2: H / 2})); return svg; }
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (o.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (hi === lo) { hi += 1; lo -= 1; }
  const X = (i) => pad + (i / (vals.length - 1)) * (W - 2 * pad);
  const Y = (v) => pad + (1 - (v - lo) / (hi - lo)) * (H - 2 * pad);
  const d = vals.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(" ");
  if (o.zero && lo < 0 && hi > 0) svg.append(s("line", {class: "lv-sp-zero", x1: 0, x2: W, y1: Y(0), y2: Y(0)}));
  if (o.area) svg.append(s("path", {class: "lv-sp-area", d: `${d} L${X(vals.length - 1).toFixed(1)} ${H} L${X(0).toFixed(1)} ${H} Z`}));
  svg.append(s("path", {class: "lv-sp-ln", d, "vector-effect": "non-scaling-stroke"}));
  if (o.dots) vals.forEach((v, i) => svg.append(s("circle", {class: "lv-sp-dot", cx: X(i), cy: Y(v), r: 1.8})));
  return svg;
}
/** svgOf(cls, W, H, label, [[tag, attrs, text?], ...]) -> <svg> scaled to its box (text stays text). */
export function svgOf(cls, W, H, label, parts) {
  return s("svg", {class: cls, viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": label},
    parts.map(([tag, attrs, text]) => s(tag, attrs, text == null ? null : String(text))));
}
/** bars(values, {w, h, cls, flags}) -> <svg>: one bar per value (data check: seconds per tick, flagged ones marked). */
export function barSpark(vals, o = {}) {
  const W = o.w || 400, H = o.h || 60;
  const xs = (vals || []).map(Number);
  const svg = s("svg", {class: ["lv-bars", o.cls], viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": o.label || "막대 그래프"});
  const hi = Math.max(1, ...xs.filter(Number.isFinite));
  const bw = W / Math.max(1, xs.length);
  xs.forEach((v, i) => {
    if (!Number.isFinite(v)) return;
    const bh = Math.max(1, (v / hi) * (H - 2));
    svg.append(s("rect", {class: ["lv-bar", o.flags && o.flags[i] ? "flag" : ""], x: (i * bw).toFixed(2), y: (H - bh).toFixed(2),
      width: Math.max(0.6, bw - 0.6).toFixed(2), height: bh.toFixed(2)}));
  });
  return svg;
}
/** The long / short vote bar of one strategy x timeframe: "롱 12 ▮▮▮▯ 숏 3" over its settings. */
export function voteBar(long, short, total, o = {}) {
  const L = Number(long) || 0, S = Number(short) || 0, T = Math.max(1, Number(total) || L + S || 1);
  const scale = o.scale || Math.max(L, S, 1);
  const w = (n) => `${Math.min(100, (n / scale) * 100).toFixed(1)}%`;
  return h("div", {class: ["lv-vote", o.cls], role: "img",
    "aria-label": `롱 ${L}개, 숏 ${S}개 (설정 ${fmt.int(T)}개 중)`, title: `설정 ${fmt.int(T)}개 중 이번 봉에서 롱 신호 ${L}개 · 숏 신호 ${S}개`},
  h("span", {class: "lv-vk up num"}, `롱 ${fmt.int(L)}`),
  h("span", {class: "lv-vt"}, h("i", {class: "lv-vl", style: {width: w(L)}}), h("i", {class: "lv-vs", style: {width: w(S)}})),
  h("span", {class: "lv-vk down num"}, `숏 ${fmt.int(S)}`));
}

// ---------------------------------------------------------------- a sortable table
/** sortTable(cols, rows, {sort: {key, desc}, onSort(sort), onRow(row), rowCls, cls}) -> table in its scroll box.
 *  cols: [{key, label, l, cls, get(row) -> text|Node, val(row) -> number|string (sorting), title}] */
export function sortTable(cols, rows, o = {}) {
  const sort = o.sort || {};
  const col = cols.find((c) => c.key === sort.key && c.val);
  const list = col ? [...rows].sort((a, b) => {
    const x = col.val(a), y = col.val(b);
    const nx = x == null || (typeof x === "number" && !Number.isFinite(x)), ny = y == null || (typeof y === "number" && !Number.isFinite(y));
    if (nx || ny) return nx === ny ? 0 : nx ? 1 : -1;
    const c = typeof x === "string" ? x.localeCompare(y, "ko") : x - y;
    return sort.desc ? -c : c;
  }) : rows;
  const head = h("tr", null, cols.map((c) => {
    const on = c.key === sort.key;
    const label = c.val ? h("button", {type: "button", class: "lv-th", "aria-label": `${c.label}로 정렬`, onclick: () => {
      if (o.onSort) o.onSort({key: c.key, desc: on ? !sort.desc : c.l ? false : true});
    }}, c.label, on ? h("span", {class: "lv-sortk", "aria-hidden": "true"}, sort.desc ? " ▼" : " ▲") : null) : c.label;
    return h("th", {class: [c.l ? "l" : "", c.hcls], title: c.title, scope: "col", "aria-sort": on ? (sort.desc ? "descending" : "ascending") : null}, label);
  }));
  return h("div", {class: ["tbl-wrap", o.wrapCls]}, h("table", {class: ["tbl", "lv-tbl", o.cls]},
    h("thead", null, head),
    h("tbody", null, list.map((r) => {
      const tr = h("tr", {class: [o.onRow ? "click" : "", o.rowCls ? o.rowCls(r) : ""]},
        cols.map((c) => { const v = c.get(r); return h("td", {class: [c.l ? "l" : "", typeof c.cls === "function" ? c.cls(r) : c.cls]}, v instanceof Node ? v : v ?? "—"); }));
      if (o.onRow) {
        tr.tabIndex = 0;
        tr.addEventListener("click", (e) => { if (!(e.target && e.target.closest && e.target.closest("a, button"))) o.onRow(r); });
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter") o.onRow(r); });
      }
      return tr;
    }))));
}

/** Open positions as small cards (a phone: the wide table's key numbers without sideways scrolling). Each card opens
 *  the trade chart. o: {ctx, priceOf(coin), from} */
export function posCards(rows, o) {
  return h("div", {class: "lv-pcards"}, rows.map((p) => {
    const price = o.priceOf(p.coin), u = liveUnreal(p, price), uv = fmt.money(u, true);
    const r = Number(p.margin) && u != null ? u / Number(p.margin) : null, rv = fmt.ratio(r);
    return h("a", {class: "lv-pcard", href: tradeHref(o.ctx, p, o.from)},
      h("div", {class: "lv-pc1"}, h("b", null, fmt.coin(p.coin)), sideTag(p.side), h("span", {class: "muted"}, fmt.lev(p.L)),
        h("span", {class: "grow"}), h("b", {class: ["num", fmt.tone(u, uv)]}, uv)),
      h("div", {class: "lv-pc2"}, h("span", {class: "lv-pcn"}, p.name || p.id), h("span", {class: ["num", fmt.tone(r, rv)]}, rv)),
      h("div", {class: "lv-pc3"}, `진입 ${px(p.entry)} → 지금 ${px(price ?? p.last)} · 손절까지 ${stopText(p, price)} · 보유 ${fmt.dur(Number(p.held_ms) / 1000)}`));
  }));
}

/** A thin panel in the terminal look: head (title, sub, actions) + body. */
export function panel(title, o = {}, ...kids) {
  const sub = h("span", {class: "lv-phs"}, o.sub || "");
  const head = h("div", {class: "lv-ph"}, h("h2", null, title), sub, h("span", {class: "grow"}), ...(o.acts || []));
  const body = h("div", {class: ["lv-pb", o.scroll ? "scroll" : ""]}, kids);
  const el = h("section", {class: ["lv-p", o.cls], "aria-label": o.label || title}, head, body);
  el.sub = sub; el.body = body; el.head = head;
  return el;
}

/** The live-data line of a screen ("바이낸스 시세 · 5초마다" / "가짜 시세" / "꺼짐" / "받지 못함 · 12초 전 값"). */
export function liveNote(d) {
  if (!d) return "시세 불러오는 중";
  if (d.off) return "실시간 시세 꺼짐 (DEMOBOT_DASH_LIVE=off)";
  if (d.unavailable) return "바이낸스 시세를 받지 못함 · 잠시 뒤 다시 시도";
  const src = d.source === "fake" ? "연습용 가짜 시세 (DEMOBOT_DASH_LIVE=fake)" : "바이낸스 공개 시세";
  return d.stale ? `${src} · 새로 받지 못해 ${age(d.generated_ms)} 전 값` : src;
}

// ---------------------------------------------------------------- the candle chart with positions and trades
function kstTick(t, type) {
  const d = new Date(t * 1000 + 9 * 3.6e6), two = (x) => String(x).padStart(2, "0");
  if (type === 0) return String(d.getUTCFullYear());
  if (type === 1) return `${d.getUTCMonth() + 1}월`;
  if (type === 2) return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
  return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
}
const kstTime = (t) => {
  const d = new Date(t * 1000 + 9 * 3.6e6), two = (x) => String(x).padStart(2, "0");
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
};

/**
 * liveChart(box, {volume, compact}) -> {set(bars, tf), lines(groups, opts), marks(list), tick(price), dispose(), last()}
 *   bars: /api/klines "bars" ({t, o, h, l, c, v}); groups: groupEntries() of this coin; marks: [{t_ms, kind: "in"|"win"|"loss", side, n}]
 */
export async function liveChart(box, o = {}) {
  const LW = await loadLwc();
  let dec = 2, tf = "15m";
  const chart = LW.createChart(box, {
    width: box.clientWidth, height: box.clientHeight,
    layout: {background: {color: tok("--surface")}, textColor: tok("--ink-2"), fontSize: o.compact ? 11 : 12, fontFamily: tok("--f-body")},
    grid: {vertLines: {color: tok("--line")}, horzLines: {color: tok("--line")}},
    rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.08, bottom: o.volume ? 0.2 : 0.08}},
    timeScale: {borderColor: tok("--line-2"), timeVisible: true, secondsVisible: false, tickMarkFormatter: kstTick, rightOffset: 4},
    crosshair: {mode: 0},
    localization: {locale: "ko-KR", priceFormatter: (p) => fmt.num(p, dec), timeFormatter: kstTime},
    handleScroll: {vertTouchDrag: false}, handleScale: {axisPressedMouseMove: false},
  });
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => chart.resize(box.clientWidth, box.clientHeight)) : null;
  if (ro) ro.observe(box);
  const up = color("--up"), down = color("--down");
  const candles = chart.addCandlestickSeries({upColor: up, downColor: down, borderUpColor: up, borderDownColor: down,
    wickUpColor: up, wickDownColor: down, priceLineVisible: true, priceLineColor: color("--accent"), priceLineStyle: 2, lastValueVisible: true});
  let vol = null;
  if (o.volume) {
    vol = chart.addHistogramSeries({priceScaleId: "vol", priceFormat: {type: "volume"}, lastValueVisible: false, priceLineVisible: false});
    chart.priceScale("vol").applyOptions({scaleMargins: {top: 0.84, bottom: 0}});
  }
  const volUp = color("--vol-up", "--up"), volDn = color("--vol-down", "--down");
  let data = [], plines = [], lastKey = "";
  const barTime = (ms) => {
    if (!data.length || ms == null) return null;
    const sec = Math.floor(Number(ms) / 1000);
    if (sec < data[0].time) return null;
    let lo = 0, hi = data.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (data[mid].time <= sec) lo = mid; else hi = mid - 1; }
    return data[lo].time;
  };
  const api = {
    chart,
    /** bars of one timeframe; keep: keep the viewer's scroll position (a refresh of the same coin and timeframe) */
    set(bars, newTf, keep) {
      tf = newTf || tf;
      const b = bars || {};
      const t = b.t || [];
      const out = [], vs = [];
      for (let i = 0; i < t.length; i++) {
        const row = [t[i], b.o[i], b.h[i], b.l[i], b.c[i]].map(Number);
        if (row.some((x) => !Number.isFinite(x))) continue;
        const time = Math.floor(row[0] / 1000);
        if (out.length && time <= out[out.length - 1].time) continue;
        out.push({time, open: row[1], high: row[2], low: row[3], close: row[4]});
        if (vol) vs.push({time, value: Number(b.v && b.v[i]) || 0, color: row[4] >= row[1] ? volUp : volDn});
      }
      data = out;
      dec = priceDec(out.length ? out[out.length - 1].close : 1);
      candles.applyOptions({priceFormat: {type: "price", precision: dec, minMove: Math.pow(10, -dec)}});
      const range = keep ? chart.timeScale().getVisibleLogicalRange() : null;
      candles.setData(out);
      if (vol) vol.setData(vs);
      if (range) chart.timeScale().setVisibleLogicalRange(range);
      else if (out.length) {
        const n = o.compact ? 90 : Math.max(50, Math.min(200, Math.round(box.clientWidth / 6)));
        chart.timeScale().setVisibleLogicalRange({from: Math.max(0, out.length - n), to: out.length + 3});
      }
    },
    last: () => (data.length ? data[data.length - 1] : null),
    /** the newest bars of a poll ({t, o, h, l, c, v}, e.g. limit=2): the forming bar replaced, a new bar added */
    merge(bars) {
      const b = bars || {}, t = b.t || [];
      for (let i = 0; i < t.length; i++) {
        const row = [t[i], b.o[i], b.h[i], b.l[i], b.c[i]].map(Number);
        if (row.some((x) => !Number.isFinite(x)) || !data.length) continue;
        const time = Math.floor(row[0] / 1000), last = data[data.length - 1];
        if (time < last.time) continue;
        const bar = {time, open: row[1], high: row[2], low: row[3], close: row[4]};
        if (time === last.time) data[data.length - 1] = bar; else data.push(bar);
        candles.update(bar);
        if (vol) vol.update({time, value: Number(b.v && b.v[i]) || 0, color: bar.close >= bar.open ? volUp : volDn});
      }
    },
    /** show or hide the volume bars (a chart made with {volume: true}) */
    volume(on) {
      if (!vol) return;
      vol.applyOptions({visible: !!on});
      candles.priceScale().applyOptions({scaleMargins: {top: 0.08, bottom: on ? 0.2 : 0.08}});
    },
    /** the forming bar follows the live price (only while it really is the forming bar) */
    tick(price) {
      const p = Number(price);
      if (!data.length || !Number.isFinite(p) || p <= 0) return;
      const b = data[data.length - 1];
      if (Date.now() >= (b.time * 1000) + (TF_MS[tf] || 0)) return;
      const nb = {time: b.time, open: b.open, high: Math.max(b.high, p), low: Math.min(b.low, p), close: p};
      data[data.length - 1] = nb;
      candles.update(nb);
    },
    /** our open positions on this coin: one line per account entry (its leverage lines share it); the labels go to
     *  the `labels` entries nearest the price; stops / targets only when asked */
    lines(groups, opt = {}) {
      const key = JSON.stringify([groups.map((g) => [g.id, g.entry_ms, g.Ls.length]), opt.stops, opt.targets, opt.labels, opt.price ? Math.round(Math.log(Number(opt.price)) * 400) : 0]);
      if (key === lastKey) return;
      lastKey = key;
      for (const pl of plines) candles.removePriceLine(pl);
      plines = [];
      const price = Number(opt.price) || (data.length ? data[data.length - 1].close : 0);
      const near = [...groups].sort((a, b) => Math.abs(a.entry - price) - Math.abs(b.entry - price));
      const labelled = new Set(near.slice(0, opt.labels == null ? 5 : opt.labels));
      const onAxis = new Set(near.slice(0, 3));
      for (const g of groups) {
        const long = g.side > 0, lab = labelled.has(g);
        const title = lab ? `${long ? "롱" : "숏"} ${levText(g.Ls)} · ${stopText(g, price)} 손절` : "";
        plines.push(candles.createPriceLine({price: Number(g.entry), color: color(long ? "--up" : "--down"), lineWidth: 1, lineStyle: 0,
          axisLabelVisible: lab && onAxis.has(g) && !o.compact, title}));
        if (opt.stops && Number.isFinite(Number(g.stop))) {
          plines.push(candles.createPriceLine({price: Number(g.stop), color: color("--warn"), lineWidth: 1, lineStyle: 2, axisLabelVisible: false,
            title: lab ? "손절" : ""}));
        }
        const tgt = g.target != null ? g.target : (targetR(g.exit_ko) != null ? Number(g.entry) + g.side * targetR(g.exit_ko) * Math.abs(g.entry - g.stop) : null);
        if (opt.targets && tgt != null && Number.isFinite(Number(tgt))) {
          plines.push(candles.createPriceLine({price: Number(tgt), color: color("--accent"), lineWidth: 1, lineStyle: 1, axisLabelVisible: false,
            title: lab ? "목표" : ""}));
        }
      }
    },
    /** entry / exit marks of recent trades of this coin, merged per bar */
    marks(list) {
      const by = new Map();
      for (const m of list || []) {
        const time = barTime(m.t_ms);
        if (time == null) continue;
        const k = `${time}|${m.kind}|${m.kind === "in" ? m.side : ""}`;
        const x = by.get(k) || {time, kind: m.kind, side: m.side, n: 0};
        x.n += m.n || 1;
        by.set(k, x);
      }
      const out = [...by.values()].map((x) => {
        if (x.kind === "in") {
          const long = Number(x.side) > 0;
          return {time: x.time, position: long ? "belowBar" : "aboveBar", color: color("--accent"), shape: long ? "arrowUp" : "arrowDown",
            text: `${long ? "롱" : "숏"}${x.n > 1 ? " ×" + x.n : ""}`};
        }
        return {time: x.time, position: "aboveBar", color: color(x.kind === "win" ? "--up" : "--down"), shape: "circle",
          text: `${x.kind === "win" ? "익" : "손"}${x.n > 1 ? " ×" + x.n : ""}`};
      }).sort((a, b) => a.time - b.time);
      candles.setMarkers(o.compact ? [] : out);
    },
    dispose() { if (ro) ro.disconnect(); try { chart.remove(); } catch (e) { /* gone */ } },
  };
  return api;
}

/** Marks for the chart from trades.json rows of one coin (one per account entry; the exit coloured by its result). */
export function tradeMarks(rows, coin) {
  const seen = new Set(), out = [];
  for (const t of rows || []) {
    if (t.coin !== coin) continue;
    const k = `${t.account}|${t.entry_ms}|${t.side}`;
    if (seen.has(k)) continue;
    seen.add(k);
    out.push({t_ms: t.entry_ms, kind: "in", side: t.side});
    if (t.status === "closed" && t.exit_ms) out.push({t_ms: Number(t.exit_ms) - 1, kind: Number(t.pnl) > 0 ? "win" : "loss"});
  }
  return out;
}

// ---------------------------------------------------------------- the P&L calendar (calendar.json; 터미널 and 흐름)
/**
 * calendar({href, cls, value, text, label}) -> {grid, day, prev, next, title, set(cal), mode({value, text, label})}: one
 * month, Monday first, a cell per KST day coloured by its value (up / down, stronger = bigger, against the month's
 * largest); ◀ ▶ step through the months that have days; a tap on a day shows its trades, P&L and best / worst line.
 * value(day) -> number (default: pnl_sum, the P&L in $ of every plain line); text(v) -> the cell's short text.
 * A day without a record is "기록 없음" (dashed), never a zero; the last day of the file is today.
 */
export function calendar(o = {}) {
  const st = {cal: null, month: null, day: null, value: o.value || ((d) => Number(d.pnl_sum) || 0), text: o.text || shortNum, label: o.label || "손익 합"};
  const title = h("span", {class: "lv-calm num"});
  const prev = h("button", {type: "button", class: "lv-calnav", "aria-label": "이전 달", onclick: () => move(-1)}, "◀");
  const next = h("button", {type: "button", class: "lv-calnav", "aria-label": "다음 달", onclick: () => move(1)}, "▶");
  const grid = h("div", {class: ["lv-cal", o.cls], role: "grid", "aria-label": "수익 캘린더"});
  const day = h("div", {class: "lv-calday"});
  const ok = () => st.cal && !st.cal.missing && Array.isArray(st.cal.days) && st.cal.days.length;
  const months = () => (ok() ? [...new Set(st.cal.days.map((d) => String(d.day).slice(0, 7)))].sort() : []);
  function move(k) {
    const ms = months(), i = ms.indexOf(st.month);
    if (i < 0) return;
    const j = Math.max(0, Math.min(ms.length - 1, i + k));
    if (j !== i) { st.month = ms[j]; paint(); }
  }
  const link = (r, word) => (r && r.id ? h("div", {class: "lv-cdl muted"}, `${word} `,
    o.href ? h("a", {href: o.href("account", r.id)}, `${r.name || r.id} ${r.L}배`) : `${r.name || r.id} ${r.L}배`, ` ${fmt.money(r.pnl, true)}`) : null);
  function paint() {
    if (!st.cal) { put(grid, h("p", {class: "empty"}, "불러오는 중")); return; }
    if (!ok()) { put(grid, h("div", {class: "lv-pnone"}, h("b", null, "준비 중"), " · 날마다 기록이 아직 없습니다")); title.textContent = ""; put(day); return; }
    const days = st.cal.days, ms = months();
    if (!ms.includes(st.month)) st.month = ms[ms.length - 1];
    const byDay = new Map(days.map((d) => [String(d.day), d]));
    const today = String(days[days.length - 1].day);
    if (!st.day || !byDay.has(st.day)) st.day = today;
    const [y, m] = st.month.split("-").map(Number);
    title.textContent = `${y}년 ${m}월`;
    prev.disabled = ms.indexOf(st.month) <= 0;
    next.disabled = ms.indexOf(st.month) >= ms.length - 1;
    const pad = (new Date(Date.UTC(y, m - 1, 1)).getUTCDay() + 6) % 7;
    const n = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const inMonth = days.filter((d) => String(d.day).startsWith(st.month));
    const maxAbs = Math.max(1e-9, ...inMonth.map((d) => Math.abs(st.value(d) || 0)));
    const cells = ["월", "화", "수", "목", "금", "토", "일"].map((w, i) => h("span", {class: ["lv-cw", i >= 5 ? "we" : ""]}, w));
    for (let i = 0; i < pad; i++) cells.push(h("span", {class: "lv-cc pad", "aria-hidden": "true"}));
    for (let dd = 1; dd <= n; dd++) {
      const key = `${st.month}-${String(dd).padStart(2, "0")}`;
      const d = byDay.get(key);
      if (!d) {
        const later = key > today;                                    // a day still to come is not "기록 없음"
        cells.push(h("span", {class: ["lv-cc", later ? "later" : "none"], title: `${m}/${dd}: ${later ? "아직 오지 않은 날" : "기록 없음"}`}, h("span", {class: "dn"}, String(dd))));
        continue;
      }
      const v = st.value(d) || 0;
      const tone = !d.trades || v === 0 ? "flat" : v > 0 ? "up" : "down";
      cells.push(h("button", {type: "button", class: ["lv-cc", tone, key === today ? "today" : "", key === st.day ? "on" : ""],
        style: {"--a": (0.1 + 0.55 * Math.min(1, Math.abs(v) / maxAbs)).toFixed(3)},
        title: `${m}/${dd}: 거래 ${fmt.int(d.trades)}건 · ${st.label} ${st.text(v)} · 오른 줄 ${fmt.int(d.lines_up)} · 내린 줄 ${fmt.int(d.lines_down)}`,
        "aria-pressed": String(key === st.day), onclick: () => { st.day = key; paint(); }},
      h("span", {class: "dn"}, String(dd)), h("span", {class: "dv num"}, d.trades ? st.text(v) : "—")));
    }
    put(grid, cells);
    const d = byDay.get(st.day);
    if (!d) { put(day); return; }
    const v = fmt.money(d.pnl_sum, true);
    put(day, h("div", {class: "lv-cdl"}, h("b", null, String(d.day).slice(5).replace("-", "/")), " · 거래 ", h("b", {class: "num"}, fmt.int(d.trades)),
      "건 · 손익 합 ", h("b", {class: ["num", fmt.tone(d.pnl_sum, v)]}, v), ` · 오른 줄 ${fmt.int(d.lines_up)} · 내린 줄 ${fmt.int(d.lines_down)}`),
    link(d.best, "가장 잘 된 줄"), link(d.worst, "가장 안 된 줄"));
  }
  return {grid, day, prev, next, title,
    set(cal) { st.cal = cal || null; paint(); },
    mode(m) { if (m.value) st.value = m.value; if (m.text) st.text = m.text; if (m.label) st.label = m.label; paint(); }};
}

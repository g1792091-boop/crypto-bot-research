// 실거래 › 지도 (#/livebots/map, owners 10/19 "간지나게"): where the three accounts stand against what the 5-year research
// says is likely, and where the paper account wins and loses (/api/v4/livebots/map, dash/more/livebots.py map_view()).
//   기대 범위 띠  x = closed trades, y = wins so far. The honest band (the twin fitted on 2020-24 only, read on unseen
//                2025-26: the realistic range, 5-95 %) filled; the fitted band (the 5-year backtest, optimistic) lighter;
//                both medians thin; break-even dashed; the 40-trade checkpoint; the accounts' step lines (페이퍼(연습),
//                바이비트, MEXC) with end dots and labels. One sentence per account: inside / below / above the honest
//                range (below its 5 % edge = the line the drift alarm uses: livecheck drift_conditions, last 20 / 40).
//                A pointer or the arrow keys read the bands at any trade count.
//   어디서 벌고 어디서 잃나  the paper account's record by BTC 4h regime, coin, Korea-time 4-hour block and side next to the
//                5-year number of the same cut (liveimprove's own cuts and status words); a cut is coloured from 10
//                trades on, grey before; the 4-hour blocks also as a 24-hour ring with the Korea-time hand.
//   숫자 읽는 법  fitted vs realistic, break-even, how much luck a few trades hold (from the bands themselves).
// HONESTY: nothing is drawn that the server did not send; a source that is not there says 수집 전 / 못 읽음 with its reason;
// before the first trade only the bands are drawn ("거래가 쌓이면 여기에 선이 그려져요"); a failed refresh keeps the last
// answer dimmed with its age. The pure functions below (bands, scales, tones, the ring) are tested in node.
// 추세판단 봇 (the server's kind "trend", owners 10/21): a new rule set has no backtest, so there is no band, no 5-year
// column and no status word; the page says why (band_ko) in the band's place. The hero becomes 이긴 횟수 (each account's
// wins so far, from the bot's start, no range); the split is the bot's own trades by the judgment it entered on (4 of 4 /
// 3 of 4), coin, KST 4-hour block, side and entry bar (the server's cut_defs), each row with its money (연습) where the
// 5-year number was, coloured by its sign from 10 trades on (grey before) and 표본 적음 under 20.
// (The band chart, the ring and the side split are the same drawings.) Before its first closed trade (the server's
// ``empty``, owners 10/21 night: zeros everywhere on the first day) one card says so in their place, with what the 7/1~10/20
// replay says to expect (가상).
import {h, s, put, ui, fmt, motion, serverNow, href} from "../core/pb.js";
import {acctKo, acctTag, sourceState, expectLines, expectHead, eraWords, EXEC_SLOTS, execsNow} from "./livebots-kit.js";

export const MAP_API = "/api/v4/livebots/map";
const REFRESH_MS = 30 * 1000;
const IDS = ["paper", "bybit", "mexc"];
const SHORT = {paper: "페이퍼", bybit: "바이비트", mexc: "WOO X Pro", deepcoin: "딥코인", wooxpro2: "WOO X Pro 2", toobit: "투비트"};
/** The accounts of an answer's band: the second paper bot's line too while the server sends it (owners 10/23: the 'VWAP
 *  개선판', its own wins from its own start, named by its bot), the third executor's (딥코인) while the server has it;
 *  one paper bot and two executors: the three as before. */
export const idsOf = (b) => ["paper", ...(b && b.accounts && b.accounts.paper2 ? ["paper2"] : []),
  ...EXEC_SLOTS.filter((id) => execsNow().includes(id) || (b && b.accounts && b.accounts[id]))];
/** A line's short label: the account's (페이퍼 · 바이비트 · WOO X Pro); with a second paper bot both paper lines by their
 *  bots' names (acctKo: the summary's names). */
const shortOf = (id, b) => (id === "paper2" ? ((b && b.accounts && b.accounts.paper2 && b.accounts.paper2.label_ko) || acctKo(id))
  : id === "paper" && b && b.accounts && b.accounts.paper2 ? acctKo(id) : SHORT[id] || id);
/** liveimprove SMALL_N: a cut is judged (and coloured here) from this many live trades. */
export const MIN_N = 10;
const SMALL_ACCT = 20;                   // an account's line: fewer closed trades than this is mostly luck (표본 적음)
const CHECK_N = 40;                      // the owners' first real checkpoint (livecheck CHECK_N)
const HOUR = 3600 * 1000;
const KST = 9 * HOUR;
export const CUTS = [
  {id: "reg5", ko: "장세", sub: "BTC 4시간 흐름"},
  {id: "coin", ko: "코인", sub: "6개 코인"},
  {id: "hb", ko: "시간대", sub: "한국 시간 4시간씩"},
  {id: "side", ko: "방향", sub: "롱 · 숏"},
];
const STATUS_TONE = {"표본 작음": "thin", "기대 안": "", "주의": "warn", "확실히 나쁨": "bad"};
const STATUS_TIP = {
  "표본 작음": "거래 10번 미만: 판단하지 않아요",
  "기대 안": "현실 기대(처음 보는 기간 승률)와 견줘 운으로 설명되는 범위",
  "주의": "현실 기대보다 덜 이김: 운으로는 5%보다 드문 일 (여러 줄을 보면 운만으로도 가끔 나와요)",
  "확실히 나쁨": "여러 줄을 함께 본 엄격한 기준으로도 현실 기대보다 확실히 덜 이김",
};
const TONE_KO = {hi: "5년만큼 이김", ok: "본전 위", lo: "현실 기대 근처 · 본전 아래", bad: "현실 기대 아래", small: "표본 적음", none: "아직 거래 없음"};
/** The trend bot's colours: the row's money (연습) by its sign, from MIN_N trades on. */
const TREND_TONE_KO = {ok: "번 쪽 (손익 +)", bad: "잃은 쪽 (손익 −)", lo: "본전", small: "표본 적음 (10번 미만)", none: "아직 거래 없음"};
const SMALL_ROW = 20;                    // 표본 적음 under 20 trades (the site's floor)

// ================================================================ pure functions (node tests)
const f1 = (v) => (Math.round(v * 10) / 10).toFixed(1);

/** The smallest k with P(X <= k) >= q for each q (sorted), X ~ Binomial(n, p): the server's binom_quantiles, in log space
 *  (no underflow for long runs). null for a rate that is not a probability. */
export function binomQ(n, p, qs = [0.05, 0.5, 0.95]) {
  if (!(p > 0 && p < 1) || !(n >= 0)) return null;
  const N = Math.round(n), want = [...qs].sort((a, b) => a - b), out = [];
  const lp = Math.log(p), lq = Math.log1p(-p);
  let l = N * lq, c = 0, i = 0;
  for (let k = 0; k <= N && i < want.length; k++) {
    if (k > 0) l += Math.log(N - k + 1) - Math.log(k) + lp - lq;
    c += Math.exp(l);
    while (i < want.length && c >= want[i] - 1e-12) { out.push(k); i++; }
  }
  while (out.length < want.length) out.push(N);
  return out;
}

/** The bands at trade count n: {honest: [p5, p50, p95] | null, fit: [...] | null, be: wins at break-even | null}. The
 *  server's arrays where it worked n out, else the same quantiles computed here. */
export function bandAt(band, n) {
  if (!band || !(n >= 0)) return {honest: null, fit: null, be: null};
  if (n === 0) return {honest: band.honest_band ? [0, 0, 0] : null, fit: band.fit_band ? [0, 0, 0] : null, be: band.break_even != null ? 0 : null};
  const i = (band.ns || []).indexOf(n);
  const pick = (arr, p) => (arr && i >= 0 && arr[i] ? arr[i] : arr ? binomQ(n, p, band.qs || undefined) : null);
  return {honest: pick(band.honest_band, band.honest), fit: pick(band.fit_band, band.fit), be: band.break_even != null ? band.break_even * n : null};
}

/** Where an account's wins so far stand against the honest range at its trade count: "below" (under the 5 % edge: the
 *  drift alarm's line) | "inside" | "above" | "none" (no closed trade) | "unknown" (no honest band). */
export function whereOf(acc, band) {
  if (!acc || !acc.n) return {where: "none", n: 0, wins: 0};
  const q = bandAt(band, acc.n);
  const base = {n: acc.n, wins: acc.wins, rate: acc.rate != null ? acc.rate : acc.wins / acc.n, q};
  if (!q.honest) return {...base, where: "unknown"};
  return {...base, where: acc.wins < q.honest[0] ? "below" : acc.wins > q.honest[2] ? "above" : "inside"};
}
const WHERE_KO = {below: "현실 기대 범위 아래", inside: "현실 기대 범위 안", above: "현실 기대 범위 위"};
const WHERE_CHIP = {below: ["범위 아래", "warn"], inside: ["범위 안", "thin"], above: ["범위 위", "accent"]};

/** "페이퍼 48번 중 31번 이김 (64.6%) · 현실 기대 범위 아래" (and its tone: warn below the honest 5 % edge). */
export function acctSentence(id, acc, band) {
  const w = whereOf(acc, band);
  const name = shortOf(id, band);
  if (w.where === "none") return {text: `${name} 아직 닫힌 거래 없음`, tone: "none", where: "none"};
  const head = `${name} ${fmt.int(w.n)}번 중 ${fmt.int(w.wins)}번 이김 (${fmt.pct(w.rate, 1, false)})`;
  if (w.where === "unknown") return {text: head, tone: "", where: "unknown"};
  return {text: `${head} · ${WHERE_KO[w.where]}`, tone: w.where === "below" ? "warn" : w.where === "above" ? "up" : "", where: w.where};
}

/** A round step for about `count` grid lines up to max. */
export function niceStep(max, count = 4) {
  for (const st of [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000]) if (max / st <= count) return st;
  return Math.ceil(max / count);
}

/** Labels at the end of the lines, pulled apart to at least `gap` px and kept inside [lo, hi]: ys in, ys out (same order). */
export function spread(ys, gap = 16, lo = 0, hi = Infinity) {
  const idx = ys.map((y, i) => [y, i]).sort((a, b) => a[0] - b[0]);
  const out = idx.map(([y]) => Math.max(lo, Math.min(hi, y)));
  for (let k = 1; k < out.length; k++) if (out[k] - out[k - 1] < gap) out[k] = out[k - 1] + gap;
  const over = out.length ? out[out.length - 1] - hi : 0;
  if (over > 0) for (let k = out.length - 1; k >= 0; k--) { out[k] -= over; if (k && out[k] - out[k - 1] >= gap) break; }
  for (let k = out.length - 2; k >= 0; k--) if (out[k + 1] - out[k] < gap) out[k] = out[k + 1] - gap;
  const res = new Array(ys.length);
  idx.forEach(([, i], k) => { res[i] = out[k]; });
  return res;
}
/** Rough width of a short SVG label at the 12 px token (Hangul about 12 px, the rest about 7 px). */
export const labelW = (t) => [...String(t)].reduce((a, ch) => a + (ch.charCodeAt(0) > 0x2e80 ? 12 : 7), 0);

/** A cumulative-wins step line: from (0, 0), at trade i the line moves to x = i, then up when that trade won. */
export function stepPath(points, X, Y) {
  let d = `M${f1(X(0))},${f1(Y(0))}`, w0 = 0;
  for (const [i, w] of points || []) {
    d += `H${f1(X(i))}`;
    if (w !== w0) d += `V${f1(Y(w))}`;
    w0 = w;
  }
  return d;
}

/**
 * Everything the 기대 범위 띠 draws, in pixels for a W x H box: scales, the two bands (area between p5 and p95, the
 * median), the honest band's lower edge (the alarm line), break-even, the checkpoint, grid ticks and each account's
 * step line with its end dot and label. band: the server's `band`; ids: the accounts to draw, in order.
 */
export function bandGeom(band, W = 640, H = 300, ids = IDS) {
  const pad = {l: 36, r: 14, t: 14, b: 28};
  const nMax = Math.max(1, band.n_max || CHECK_N);
  const ns = [0, ...(band.ns || [])];
  const accts = ids.map((id) => [id, (band.accounts || {})[id]]).filter(([, a]) => a && a.points && a.points.length);
  const last = (b) => (b && b.length ? b[b.length - 1][2] : 0);
  const top = Math.max(4, last(band.fit_band), last(band.honest_band), ...accts.map(([, a]) => a.wins),
    band.break_even ? band.break_even * nMax : 0);
  const yStep = niceStep(top, H < 280 ? 4 : 5), yMax = Math.max(yStep, top * 1.06);
  const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
  const X = (n) => pad.l + (n / nMax) * pw;
  const Y = (w) => pad.t + (1 - w / yMax) * ph;
  const row = (b, k) => (k === 0 ? [0, 0, 0] : b[k - 1]);
  const line = (b, j) => ns.map((n, k) => `${k ? "L" : "M"}${f1(X(n))},${f1(Y(row(b, k)[j]))}`).join("");
  const area = (b) => {
    if (!b) return null;
    const up = ns.map((n, k) => `${k ? "L" : "M"}${f1(X(n))},${f1(Y(row(b, k)[2]))}`).join("");
    const down = ns.slice().reverse().map((n, k) => `L${f1(X(n))},${f1(Y(row(b, ns.length - 1 - k)[0]))}`).join("");
    return up + down + "Z";
  };
  const xStep = niceStep(nMax, W < 480 ? 4 : 8);
  const xt = [];
  for (let n = 0; n <= nMax; n += xStep) xt.push(n);
  const yt = [];
  for (let w = 0; w <= yMax + 1e-9; w += yStep) yt.push(w);
  const ends = accts.map(([id, a]) => ({id, n: a.n, wins: a.wins, x: X(a.n), y: Y(a.wins), label: `${shortOf(id, band)} ${a.wins}/${a.n}`}));
  const ly = spread(ends.map((e) => e.y), 16, pad.t + 6, H - pad.b - 4);
  ends.forEach((e, k) => {
    e.ly = ly[k];
    const wl = labelW(e.label);
    e.side = e.x + 8 + wl <= W - pad.r ? "r" : "l";
    e.lx = e.side === "r" ? e.x + 8 : e.x - 8;
  });
  return {
    W, H, pad, nMax, yMax, X, Y, xt, yt,
    honest: band.honest_band ? {area: area(band.honest_band), mid: line(band.honest_band, 1), low: line(band.honest_band, 0)} : null,
    fit: band.fit_band ? {area: area(band.fit_band), mid: line(band.fit_band, 1)} : null,
    be: band.break_even != null ? {x1: X(0), y1: Y(0), x2: X(nMax), y2: Y(band.break_even * nMax)} : null,
    check: nMax >= CHECK_N && !band.trend ? X(CHECK_N) : null,          // the trend bot has no 40-trade rule
    lines: accts.map(([id, a]) => ({id, d: stepPath(a.points, X, Y)})),
    ends,
  };
}

/** What the pointer reads at trade count n: the bands there and each drawn account's wins after its n-th trade (null
 *  past its last closed trade). */
export function readAt(band, n) {
  const q = bandAt(band, n);
  const accts = {};
  for (const [id, a] of Object.entries((band && band.accounts) || {})) {
    accts[id] = a && a.points && n >= 1 && n <= a.points.length ? a.points[n - 1][1] : n === 0 && a && a.points && a.points.length ? 0 : null;
  }
  return {n, ...q, accts};
}

/** A cut row's colour against its 5-year number, from MIN_N live trades on: "hi" (as good as the 5 years or better), "ok"
 *  (above break-even), "lo" (at the realistic rate but under break-even), "bad" (under the realistic rate), "small"
 *  (fewer than MIN_N trades: grey), "none" (no trade yet). gap: live minus 5-year, in win-rate points. */
export function cellTone(r, band) {
  if (!r || !r.n) return {tone: "none", gap: null};
  const gap = r.win != null && r.bt_win != null ? r.win - r.bt_win : null;
  if (r.n < MIN_N || r.win == null) return {tone: "small", gap};
  const be = band && band.break_even != null ? band.break_even : null;
  const hon = r.honest != null ? r.honest : band && band.honest != null ? band.honest : null;
  if (r.bt_win != null && r.win >= r.bt_win) return {tone: "hi", gap};
  if (be != null && r.win >= be) return {tone: "ok", gap};
  if (hon != null && r.win >= hon) return {tone: "lo", gap};
  return {tone: hon == null && be == null ? "small" : "bad", gap};
}

/** A trend-bot row's colour (no reference: its money's sign), from minN trades on: "ok" (+), "bad" (−), "lo" (even),
 *  "small" (fewer than minN: grey), "none" (no trade yet). */
export function trendTone(r, minN = MIN_N) {
  if (!r || !r.n) return {tone: "none", gap: null};
  if (r.n < minN || r.pnl == null) return {tone: "small", gap: null};
  return {tone: r.pnl > 0 ? "ok" : r.pnl < 0 ? "bad" : "lo", gap: null};
}

/** The splits a map draws: the server's own (the trend bot's cut_defs) or the 5-year ones. */
export const cutsOf = (d) => (d && Array.isArray(d.cut_defs) && d.cut_defs.length ? d.cut_defs : CUTS);

/** A ring segment (SVG path) between radii r0 < r1 from angle a0 to a1 (degrees, clockwise from 12 o'clock). */
export function arcPath(cx, cy, r0, r1, a0, a1) {
  const pt = (r, a) => { const t = ((a - 90) * Math.PI) / 180; return `${f1(cx + r * Math.cos(t))},${f1(cy + r * Math.sin(t))}`; };
  const large = a1 - a0 > 180 ? 1 : 0;
  return `M${pt(r1, a0)}A${r1},${r1} 0 ${large} 1 ${pt(r1, a1)}L${pt(r0, a1)}A${r0},${r0} 0 ${large} 0 ${pt(r0, a0)}Z`;
}
/** Korea-time hour of day (fractional, 0-24) and its 4-hour block (0-5). */
export const kstHour = (ms) => ((((Number(ms) + KST) % (24 * HOUR)) + 24 * HOUR) % (24 * HOUR)) / HOUR;
export const kstBlock = (ms) => Math.min(5, Math.floor(kstHour(ms) / 4));

/** Where a range gauge puts its marks (fractions 0-1 of its track) for an account at n trades with w wins. */
export function gaugeGeom(q, n, w) {
  if (!q || !q.honest || !n) return null;
  const vals = [q.honest[0], q.honest[2], w, ...(q.fit ? [q.fit[0], q.fit[2]] : []), ...(q.be != null ? [q.be] : [])];
  const m = Math.max(1, Math.round(n * 0.06));
  const lo = Math.max(0, Math.min(...vals) - m), hi = Math.min(n, Math.max(...vals) + m);
  const F = (v) => (hi > lo ? (v - lo) / (hi - lo) : 0.5);
  return {lo, hi, h: [F(q.honest[0]), F(q.honest[2])], f: q.fit ? [F(q.fit[0]), F(q.fit[2])] : null, be: q.be != null ? F(q.be) : null, w: F(w)};
}

// ================================================================ the view
/** mapView(ctx) -> {el, set()}: its own endpoint, read now and every 30 s. */
export function mapView(ctx) {
  const st = {d: null, okAt: 0, sig: "", lineSig: "", at: null, geom: null};
  const stateSlot = h("div", {class: "lb-slot"});
  const srcSlot = h("div", {class: "lb-slot lbm-src"});
  const tiles = h("div", {class: "lbm-tiles"});
  const chart = h("div", {class: "lbm-chart"});
  const read = h("div", {class: "lbm-read", "aria-live": "polite"});
  const legend = h("div", {class: "lbm-legend", role: "list"});
  const alarm = h("p", {class: "lbm-alarm"});
  const cutSlot = h("div", {class: "lb-slot"});
  const cutGrid = h("div", {class: "lbm-cuts"});
  const how = h("div", {class: "lbm-how"});
  const hero = ui.card({title: "기대 범위 띠", sub: "거래 수에 따라 이긴 횟수가 있을 만한 범위 · 닫힌 거래 기준", cls: "lbm-hero"},
    srcSlot, tiles, chart, read, legend, alarm);
  const secSub = h("span", {class: "sub"}, "페이퍼(연습) 닫힌 거래를 장세·코인·시간대·방향으로 나눠 5년 백테스트 옆에");
  const howCard = ui.card({title: "숫자 읽는 법", sub: "맞춘 숫자와 현실 숫자 · 거래가 적을 때의 운", cls: "lbm-howcard"}, how);
  const footLine = h("div", {class: "lb-foot"}, ui.assumeLine(["closed"], "페이퍼(연습) A+C 합본의 닫힌 거래 · 실거래는 이긴 횟수만 (돈은 비용 탭)"));
  const secHead = h("div", {class: "lbm-sechead"}, h("h2", null, "어디서 벌고 어디서 잃나"), secSub);
  const freshSlot = h("div", {class: "lb-slot"});      // the trend bot before its first closed trade (draw)
  const body = h("div", {class: "lbm-body stack"}, freshSlot, hero, secHead,
    cutSlot, cutGrid, howCard, footLine);
  const el = h("div", {class: "lbm stack"}, stateSlot, body);
  const part = (card, cls) => { const hd = card && card.firstChild; return hd ? Array.from(hd.childNodes).find((n) => String(n.className || "") === cls || n.tagName === cls) || null : null; };
  const say = (node, text) => { if (node && node.textContent !== text) node.textContent = text; };
  const trendOn = (d) => !!(d && d.kind === "trend");
  /** The words that depend on the bot running (the trend bot: no band, its own split). */
  function botWords(d) {
    const t = trendOn(d), tb = (d && d.trend_bot) || {};
    say(part(hero, "H2"), t ? "이긴 횟수" : "기대 범위 띠");
    say(part(hero, "sub"), t ? `${tb.name || "추세판단 봇"} 시작 ${fmt.kst(tb.since)}부터 · 닫힌 거래 기준 · 기대 범위 띠 없음`
      : "거래 수에 따라 이긴 횟수가 있을 만한 범위 · 닫힌 거래 기준");
    say(secSub, t ? "추세판단 봇 닫힌 거래를 진입 때 판단·코인·시간대·방향·진입 봉으로 나눠 (백테스트 기준 없음)"
      : "페이퍼(연습) 닫힌 거래를 장세·코인·시간대·방향으로 나눠 5년 백테스트 옆에");
    say(part(howCard, "sub"), t ? "기준이 없는 새 봇의 숫자 · 거래가 적을 때의 운" : "맞춘 숫자와 현실 숫자 · 거래가 적을 때의 운");
    const fk = t ? `trend:${tb.name || ""}` : "old";
    if (footLine.dataset.k !== fk) {
      footLine.dataset.k = fk;
      put(footLine, ui.assumeLine(["closed"], t ? `페이퍼(연습) ${tb.name || "추세판단 봇"}의 닫힌 거래 · 실거래는 이긴 횟수만 (돈은 비용 탭)`
        : "페이퍼(연습) A+C 합본의 닫힌 거래 · 실거래는 이긴 횟수만 (돈은 비용 탭)"));
    }
  }
  /** The trend bot before its first closed trade (the server's ``empty``): one card in place of the hero, the splits and
   *  how to read them (all zeros on the first day), with what the replay says to expect (가상). Returns whether it is shown. */
  function drawFresh(d) {
    const e = trendOn(d) && d.empty ? d.empty : null;
    for (const x of [hero, secHead, cutSlot, cutGrid, howCard]) x.hidden = !!e;
    if (!e) { put(freshSlot); return false; }
    const ex = e.expect || {}, lines = expectLines(ex), tb = d.trend_bot || {};
    put(freshSlot, ui.card({title: "이긴 횟수 · 어디서 벌고 어디서 잃나", sub: `${tb.name || "추세판단 봇"} 시작 ${fmt.kst(e.since)}부터 · 닫힌 거래 기준`, cls: "lbm-fresh"},
      h("p", {class: "lbm-fnone"}, e.ko || "새 봇 거래 아직 없음 · 첫 거래가 닫히면 채워져요"),
      lines.length ? h("div", {class: "lbm-fexp"},
        h("p", {class: "lbm-fhead"}, ui.pill("가상 · 재현", "thin"), ` ${expectHead(ex)}`),
        h("ul", {class: "lbm-flist"}, lines.map((x) => h("li", null, x))),
        ex.note_ko ? ui.note(ex.note_ko) : null,
        h("a", {class: "lbm-fmore", href: (ctx.href || href)("livebots", "expect")}, "재현 비교 →")) : null));
    return true;
  }

  // ---------------------------------------------------------------- 기대 범위 띠
  function drawTiles(d) {
    const b = d.band;
    const ex = Object.fromEntries((d.execs || []).map((x) => [x.id, x]));
    const srcOf = (id) => (id === "paper" ? d.paper : id === "paper2" ? {state: "ok"} : ex[id] || {state: "missing"});
    put(tiles, idsOf(b).map((id) => {
      const src = srcOf(id);
      const tag = acctTag(id);
      const era = eraWords(acctKo(id), (ex[id] || {}).era);      // an executor that moved to another bot: its trend-bot trades only
      if (!src || src.state !== "ok") {
        return h("div", {class: ["lbm-tile", "lbm-a-" + id, "off"]}, h("div", {class: "lbm-th"}, tag,
          h("span", {class: "lbm-chips"}, ui.pill(src && src.state === "error" ? "못 읽음" : "수집 전", src && src.state === "error" ? "bad" : "thin"))),
        h("p", {class: "lbm-ts muted"}, (src && src.reason_ko) || (id === "paper" ? "페이퍼 DB 기록이 아직 없어요" : `${acctKo(id)} 실행기 기록이 아직 없어요`)));
      }
      const acc = b && b.accounts ? b.accounts[id] : null;
      const sen = acctSentence(id, acc, b);
      const w = whereOf(acc, b);
      const chip = WHERE_CHIP[w.where];
      const g = w.where !== "none" ? gaugeGeom(w.q, w.n, w.wins) : null;
      const lim = w.q && w.q.honest ? `현실 범위 ${fmt.int(w.q.honest[0])}~${fmt.int(w.q.honest[2])}승` : null;
      return h("div", {class: ["lbm-tile", "lbm-a-" + id, "w-" + w.where]},
        h("div", {class: "lbm-th"}, tag, id === "paper" || id === "paper2" ? null : h("span", {class: "lbm-kind real"}, "진짜 돈"),
          h("span", {class: "lbm-chips"}, w.n ? ui.smallSample(w.n, SMALL_ACCT) : null,
            chip ? ui.pill(chip[0], chip[1], w.where === "below" ? "현실 기대 범위의 아래쪽 끝(하위 5%)보다 적게 이겼어요: 감시 경보가 보는 선" : null) : null)),
        h("p", {class: ["lbm-ts", sen.tone]}, sen.text),
        id === "paper2" ? h("p", {class: "lbm-tl"}, "두 번째 페이퍼 봇 · 이 봇 시작부터 (아래 나눠 보기는 추세판단 봇만)") : null,
        era ? h("p", {class: "lbm-tl"}, era) : null,
        g ? gaugeEl(g, w) : null,
        w.n && lim ? h("p", {class: "lbm-tl"}, lim,
          w.q.be != null ? ` · 본전 ${fmt.num(w.q.be, 1)}승` : "", w.q.fit ? ` · 5년 범위 ${fmt.int(w.q.fit[0])}~${fmt.int(w.q.fit[2])}승` : "") : null);
    }));
  }
  function gaugeEl(g, w) {
    const pc = (v) => `${(v * 100).toFixed(1)}%`;
    return h("div", {class: "lbm-gauge", role: "img",
      "aria-label": `이긴 ${w.wins}번 · 현실 범위 ${w.q.honest[0]}~${w.q.honest[2]}승${w.q.fit ? ` · 5년 범위 ${w.q.fit[0]}~${w.q.fit[2]}승` : ""}`},
    g.f ? h("i", {class: "fit", style: {left: pc(g.f[0]), width: pc(Math.max(0.01, g.f[1] - g.f[0]))}}) : null,
    h("i", {class: "hon", style: {left: pc(g.h[0]), width: pc(Math.max(0.01, g.h[1] - g.h[0]))}}),
    g.be != null ? h("i", {class: "be", style: {left: pc(g.be)}}) : null,
    h("i", {class: "dot", style: {left: pc(g.w)}}),
    h("span", {class: "lo num"}, fmt.int(g.lo)), h("span", {class: "hi num"}, `${fmt.int(g.hi)}승`));
  }

  function drawChart(animate) {
    const d = st.d, b = d && d.band;
    if (!b) { put(chart); put(read); return; }
    const W = Math.max(300, Math.round(chart.clientWidth || 640));
    const H = W < 560 ? 268 : 340;
    const ids = idsOf(b).filter((id) => (b.accounts || {})[id]);
    const g = bandGeom(b, W, H, ids);
    st.geom = g;
    const empty = !g.lines.length;
    const cross = s("g", {class: "lbm-cross", "aria-hidden": "true"});
    const svg = s("svg", {class: "lbm-svg", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", tabindex: "0",
      "aria-label": b.trend ? "이긴 횟수: 거래 수에 따른 이긴 횟수 (좌우 화살표로 읽기)" : "기대 범위 띠: 거래 수에 따른 이긴 횟수와 현실 · 5년 백테스트 범위 (좌우 화살표로 읽기)"},
    s("defs", null,
      s("filter", {id: "lbm-glow", x: "-10%", y: "-10%", width: "120%", height: "120%"},
        s("feGaussianBlur", {stdDeviation: "2.2", result: "b"}), s("feMerge", null, s("feMergeNode", {in: "b"}), s("feMergeNode", {in: "SourceGraphic"}))),
      s("linearGradient", {id: "lbm-hg", x1: "0", x2: "1", y1: "0", y2: "0"}, s("stop", {offset: "0", class: "lbm-hg0"}), s("stop", {offset: "1", class: "lbm-hg1"}))),
    s("g", {class: "grid"}, g.yt.map((w) => s("line", {x1: g.pad.l, x2: W - g.pad.r, y1: f1(g.Y(w)), y2: f1(g.Y(w))})),
      g.xt.map((n) => s("line", {class: "v", x1: f1(g.X(n)), x2: f1(g.X(n)), y1: g.pad.t, y2: H - g.pad.b}))),
    s("g", {class: "ax"}, g.yt.map((w) => s("text", {class: "y", x: g.pad.l - 6, y: f1(g.Y(w) + 4)}, fmt.int(w))),
      g.xt.map((n) => s("text", {class: "x", x: f1(g.X(n)), y: H - g.pad.b + 16}, fmt.int(n))),
      s("text", {class: "xl", x: W - g.pad.r - 2, y: H - g.pad.b - 7}, "거래 수 →"), s("text", {class: "yl", x: g.pad.l + 4, y: g.pad.t + 10}, "↑ 이긴 횟수")),
    g.check != null ? s("g", {class: "chk"}, s("line", {x1: f1(g.check), x2: f1(g.check), y1: g.pad.t, y2: H - g.pad.b}),
      g.check + 70 < W - g.pad.r ? s("text", {x: f1(g.check + 4), y: g.pad.t + 24}, "40번 점검")
        : s("text", {class: "end", x: f1(g.check - 4), y: g.pad.t + 24}, "40번 점검")) : null,
    g.fit ? s("path", {class: "fitband", d: g.fit.area}) : null,
    g.honest ? s("path", {class: "honband", d: g.honest.area}) : null,
    g.fit ? s("path", {class: "fitmid", d: g.fit.mid}) : null,
    g.honest ? s("path", {class: "honmid", d: g.honest.mid}) : null,
    g.honest ? s("path", {class: "alarm", d: g.honest.low}) : null,
    g.be ? s("line", {class: "be", x1: f1(g.be.x1), y1: f1(g.be.y1), x2: f1(g.be.x2), y2: f1(g.be.y2)}) : null,
    // the empty start: the words in the empty upper left (the bands rise to the right), centred where there is room
    empty ? (W < 560 ? s("g", {class: "wait-g"}, s("text", {class: "wait start", x: g.pad.l + 10, y: g.pad.t + 46}, "거래가 쌓이면"),
      s("text", {class: "wait start", x: g.pad.l + 10, y: g.pad.t + 66}, "여기에 선이 그려져요"))
      : s("text", {class: "wait", x: f1(g.pad.l + (W - g.pad.l - g.pad.r) / 2), y: f1(g.pad.t + (H - g.pad.t - g.pad.b) * 0.3)}, "거래가 쌓이면 여기에 선이 그려져요")) : null,
    s("g", {class: "accs"}, g.lines.map((l) => s("path", {class: ["acc", "lbm-l-" + l.id], d: l.d, filter: "url(#lbm-glow)"}))),
    s("g", {class: "ends"}, g.ends.map((e) => s("g", {class: "lbm-l-" + e.id},
      s("circle", {class: "halo", cx: f1(e.x), cy: f1(e.y), r: 7}), s("circle", {class: "dot", cx: f1(e.x), cy: f1(e.y), r: 3.6}),
      Math.abs(e.ly - e.y) > 3 ? s("line", {class: "lead", x1: f1(e.x), y1: f1(e.y), x2: f1(e.side === "r" ? e.lx - 2 : e.lx + 2), y2: f1(e.ly)}) : null,
      s("text", {class: ["lab", e.side], x: f1(e.lx), y: f1(e.ly + 4)}, e.label)))),
    cross);
    put(chart, svg);
    if (animate && !empty) motion.drawIn(svg.querySelector(".accs"), 900);
    const nDef = Math.max(0, ...g.ends.map((e) => e.n)) || g.nMax;
    const n0 = st.at != null && st.at <= g.nMax ? st.at : nDef;
    const show = (n) => { drawCross(cross, g, n); drawRead(b, n); };
    show(n0);
    const nAt = (ev) => {
      const r = svg.getBoundingClientRect();
      const x = ((ev.clientX - r.left) / Math.max(1, r.width)) * W;
      return Math.max(0, Math.min(g.nMax, Math.round(((x - g.pad.l) / (W - g.pad.l - g.pad.r)) * g.nMax)));
    };
    svg.addEventListener("pointermove", (ev) => { st.at = nAt(ev); show(st.at); });
    svg.addEventListener("pointerdown", (ev) => { st.at = nAt(ev); show(st.at); });
    svg.addEventListener("pointerleave", (ev) => { if (ev.pointerType === "mouse") { st.at = null; show(nDef); } });
    svg.addEventListener("keydown", (ev) => {
      const step = ev.shiftKey ? 10 : 1;
      const cur = st.at != null ? st.at : nDef;
      const nx = ev.key === "ArrowRight" ? cur + step : ev.key === "ArrowLeft" ? cur - step : ev.key === "Home" ? 0 : ev.key === "End" ? g.nMax : null;
      if (nx == null) return;
      ev.preventDefault();
      st.at = Math.max(0, Math.min(g.nMax, nx));
      show(st.at);
    });
  }
  function drawCross(cross, g, n) {
    const r = readAt(st.d.band, n);
    const x = f1(g.X(n));
    const kids = [s("line", {class: "cl", x1: x, x2: x, y1: g.pad.t, y2: g.H - g.pad.b})];
    if (r.honest) kids.push(s("line", {class: "cr", x1: x, x2: x, y1: f1(g.Y(r.honest[2])), y2: f1(g.Y(r.honest[0]))}));
    for (const e of g.ends) {
      const w = r.accts[e.id];
      if (w != null) kids.push(s("circle", {class: ["cd", "lbm-l-" + e.id], cx: x, cy: f1(g.Y(w)), r: 3}));
    }
    cross.replaceChildren(...kids);
  }
  function drawRead(b, n) {
    const r = readAt(b, n);
    const sp = (cls, ...k) => h("span", {class: cls}, ...k);
    const acc = idsOf(b).filter((id) => (b.accounts || {})[id] && (b.accounts[id].points || []).length)
      .map((id) => sp(["lbm-rv", "lbm-a-" + id], h("i", {class: "lb-sw", "aria-hidden": "true"}), `${shortOf(id, b)} `,
        h("b", {class: "num"}, r.accts[id] == null ? "—" : `${fmt.int(r.accts[id])}승`)));
    put(read, h("b", {class: "lbm-rn num"}, `${fmt.int(n)}번째 거래`),
      r.honest ? sp("lbm-rv hon", "현실 ", h("b", {class: "num"}, `${fmt.int(r.honest[0])}~${fmt.int(r.honest[2])}승`)) : null,
      r.fit ? sp("lbm-rv fit", "5년 ", h("b", {class: "num"}, `${fmt.int(r.fit[0])}~${fmt.int(r.fit[2])}승`)) : null,
      r.be != null ? sp("lbm-rv be", "본전 ", h("b", {class: "num"}, `${fmt.num(r.be, 1)}승`)) : null, ...acc);
  }
  function drawLegend(b) {
    const li = (cls, ...k) => h("span", {class: "lbm-li", role: "listitem"}, h("i", {class: ["lbm-key", cls], "aria-hidden": "true"}), ...k);
    const drawn = idsOf(b).filter((id) => (b.accounts || {})[id] && (b.accounts[id].points || []).length);
    if (b.trend) {                                         // no band: the lines only, and what a step means
      put(legend, ...drawn.map((id) => h("span", {class: "lbm-li", role: "listitem"}, acctTag(id))));
      put(alarm, "선이 한 칸 오르면 이긴 거래, 옆으로만 가면 진 거래예요. 비교할 범위가 없어서 경보선도 없어요 (거래가 적을 때는 운이 커요).");
      return;
    }
    put(legend,
      b.honest != null ? li("hon", `현실 기대 범위 (처음 보는 2025-26 승률 ${fmt.pct(b.honest, 1, false)} · 90%가 이 안)`) : null,
      b.fit != null ? li("fit", `5년 백테스트 범위 (맞춘 승률 ${fmt.pct(b.fit, 1, false)} · 낙관)`) : null,
      li("mid", "가운데값"),
      b.break_even != null ? li("be", `본전선 (승률 ${fmt.pct(b.break_even, 1, false)})`) : null,
      li("alarm", "경보선 (현실 범위 하위 5%)"),
      ...drawn.map((id) => h("span", {class: "lbm-li", role: "listitem"}, acctTag(id))));
    put(alarm, h("b", null, "경보선"), " = 현실 기대 범위의 아래쪽 끝(하위 5%). 감시는 페이퍼의 최근 20번·40번 승리가 이 기준보다 적으면 알려요. ",
      "선이 띠 아래로 내려가면 운보다 나쁜 쪽일 수 있다는 뜻이에요 (거래가 적을 때는 운이 커요).");
  }

  // ---------------------------------------------------------------- 어디서 벌고 어디서 잃나
  const toneFor = (r, b) => (trendOn(st.d) ? trendTone(r, st.d.min_n || MIN_N) : cellTone(r, b));
  const toneWords = (t) => (trendOn(st.d) ? TREND_TONE_KO : TONE_KO)[t.tone] || "";
  function chipOf(r) {
    if (!r.n) return h("span", {class: "lbm-chip none"}, "거래 없음");
    if (trendOn(st.d)) {                                   // no reference, no status word: the sample size only
      return r.n < SMALL_ROW ? ui.smallSample(r.n, SMALL_ROW) : ui.pill(`${fmt.int(r.n)}번`, "thin", "닫힌 거래 수");
    }
    return ui.pill(r.status || "—", STATUS_TONE[r.status] || "thin", STATUS_TIP[r.status] || null);
  }
  function rowTip(r, t) {
    if (trendOn(st.d)) {
      return [r.label, r.n ? `${fmt.int(r.n)}번 중 ${fmt.int(r.wins)}번 이김 · 평균 순ROE ${fmt.pct(r.avg_roe, 1)} · 손익 ${fmt.money(r.pnl, true)} USDT (연습)` : "거래 없음",
        toneWords(t), "백테스트 기준 없음"].filter(Boolean).join(" · ");
    }
    const parts = [`${r.label}`, r.bt_n != null ? `5년 ${fmt.int(r.bt_n)}번 · 승률 ${fmt.pct(r.bt_win, 1, false)}` : "5년 기록 없음"];
    if (r.n) {
      parts.push(`지금 ${fmt.int(r.n)}번 중 ${fmt.int(r.wins)}번 이김 · 평균 ROE ${fmt.pct(r.avg_roe, 1)}`);
      if (t.gap != null) parts.push(`5년보다 ${fmt.num(t.gap * 100, 1, true)}%p`);
      parts.push(TONE_KO[t.tone] || "");
      if (r.p != null) parts.push(`운으로 이만큼 덜 이길 확률 ${fmt.pct(r.p, 1, false)}`);
      for (const [id, e] of Object.entries(r.exec || {})) {
        if (e && e.n) parts.push(`${acctKo(id)} 따라간 ${fmt.int(e.n)}번: ROE ${e.live_roe == null ? "—" : fmt.pct(e.live_roe, 1)} (페이퍼 ${e.paper_roe == null ? "—" : fmt.pct(e.paper_roe, 1)})`);
      }
    }
    return parts.filter(Boolean).join(" · ");
  }
  function meter(r, t, hon) {
    const pc = (v) => `${(Math.max(0, Math.min(1, v)) * 100).toFixed(1)}%`;
    return h("span", {class: "lbm-meter", "aria-hidden": "true"},
      r.n ? h("i", {class: "fill", style: {width: pc(r.win || 0)}}) : null,
      hon != null ? h("i", {class: "hon", style: {left: pc(hon)}}) : null,
      r.bt_win != null ? h("i", {class: "bt", style: {left: pc(r.bt_win)}}) : null);
  }
  function cutRow(r, b) {
    const t = toneFor(r, b), trend = trendOn(st.d);
    const hon = trend ? null : r.honest != null ? r.honest : b && b.honest;
    const money = r.n && r.pnl != null ? fmt.money(r.pnl, true) : "—";
    return h("div", {class: ["lbm-row", "t-" + t.tone, r.unknown ? "unk" : ""], role: "listitem", title: rowTip(r, t)},
      h("b", {class: "lbm-rl"}, r.label || String(r.key)),
      trend ? h("span", {class: "lbm-bt"}, h("b", {class: ["num", fmt.tone(r.pnl, money)]}, money), h("small", null, r.n ? "USDT" : "거래 없음"))
        : h("span", {class: "lbm-bt"}, h("b", {class: "num"}, r.bt_win == null ? "—" : fmt.pct(r.bt_win, 1, false)),
          h("small", {class: "num"}, r.bt_n == null ? "기록 없음" : `${fmt.int(r.bt_n)}번`)),
      h("span", {class: "lbm-now"},
        h("span", {class: "lbm-nv"}, h("b", {class: "num"}, r.n ? fmt.pct(r.win, 1, false) : "—"),
          h("small", {class: "num"}, r.n ? `${fmt.int(r.n)}번 · ROE ${fmt.pct(r.avg_roe, 1)}` : "아직 없음")),
        meter(r, t, hon)),
      h("span", {class: "lbm-st"}, chipOf(r)));
  }
  function ring(rows, b) {
    const S = 200, c = S / 2, r0 = 54, r1 = 80;
    const by = Object.fromEntries(rows.map((r) => [String(r.key), r]));
    const nowH = kstHour(serverNow()), nowB = kstBlock(serverNow());
    const segs = [];
    for (let k = 0; k < 6; k++) {
      const r = by[String(k)] || {key: k, n: null};
      const t = toneFor(r, b);
      segs.push(s("g", {class: ["seg", "t-" + t.tone, k === nowB ? "now" : ""]},
        s("path", {d: arcPath(c, c, r0, r1, k * 60 + 1.2, (k + 1) * 60 - 1.2)},
          s("title", null, `${r.label || `${String(k * 4).padStart(2, "0")}~${String(k * 4 + 4).padStart(2, "0")}시`} · ${r.n ? `${fmt.int(r.n)}번 · 승률 ${fmt.pct(r.win, 0, false)}` : "거래 없음"} · ${toneWords(t)}`)),
        r.n ? s("text", {class: "sv", x: f1(c + (r0 + r1) / 2 * Math.cos(((k * 60 + 30 - 90) * Math.PI) / 180)),
          y: f1(c + (r0 + r1) / 2 * Math.sin(((k * 60 + 30 - 90) * Math.PI) / 180) + 4)}, fmt.pct(r.win, 0, false)) : null));
    }
    const hand = ((nowH / 24) * 360 - 90) * (Math.PI / 180);
    const nowRow = by[String(nowB)];
    return s("svg", {class: "lbm-ring", viewBox: `0 0 ${S} ${S}`, width: S, height: S, role: "img",
      "aria-label": `24시간 시간대 고리 · 지금 한국 시간 ${fmt.hm(serverNow())} (${nowB * 4}~${nowB * 4 + 4}시 구간)`},
    s("circle", {class: "track", cx: c, cy: c, r: (r0 + r1) / 2}), ...segs,
    [0, 4, 8, 12, 16, 20].map((hh) => {
      const a = ((hh / 24) * 360 - 90) * (Math.PI / 180);
      return s("text", {class: "tk", x: f1(c + (r1 + 9) * Math.cos(a)), y: f1(c + (r1 + 9) * Math.sin(a) + 4)}, String(hh));
    }),
    s("line", {class: "hand", x1: f1(c + (r0 - 9) * Math.cos(hand)), y1: f1(c + (r0 - 9) * Math.sin(hand)),
      x2: f1(c + (r1 + 3) * Math.cos(hand)), y2: f1(c + (r1 + 3) * Math.sin(hand))}),
    s("circle", {class: "hub", cx: f1(c + (r0 - 9) * Math.cos(hand)), cy: f1(c + (r0 - 9) * Math.sin(hand)), r: 3}),
    s("text", {class: "cn", x: c, y: c - 14}, "지금"),
    s("text", {class: "cv", x: c, y: c + 6}, fmt.hm(serverNow())),
    s("text", {class: "cs", x: c, y: c + 24}, nowRow && nowRow.n ? `승률 ${fmt.pct(nowRow.win, 0, false)}` : "거래 없음"));
  }
  function sideSplit(rows) {
    const L = rows.find((r) => String(r.key) === "1"), Sx = rows.find((r) => String(r.key) === "-1");
    const nl = (L && L.n) || 0, ns = (Sx && Sx.n) || 0;
    if (!nl && !ns) return null;
    const pl = (nl / (nl + ns)) * 100;
    return h("div", {class: "lbm-split", role: "img", "aria-label": `롱 ${nl}번 · 숏 ${ns}번`},
      h("div", {class: "lbm-sbar"}, h("i", {class: "long", style: {width: `${pl.toFixed(1)}%`}}), h("i", {class: "short", style: {width: `${(100 - pl).toFixed(1)}%`}})),
      h("div", {class: "lbm-slab"}, h("span", null, "롱 ", h("b", {class: "num"}, `${fmt.int(nl)}번`)), h("span", null, "숏 ", h("b", {class: "num"}, `${fmt.int(ns)}번`))));
  }
  function drawCuts(d) {
    const b = d.band;
    const card = d.card || {};
    const trend = trendOn(d);
    put(cutSlot, card.state && card.state !== "ok" ? sourceState(card, "매매법 성적표 (페이퍼 DB · 백테스트 기준표)") : null,
      ...(card.problems || []).map((t) => h("p", {class: "lb-warn"}, t)),
      trend && d.paper && d.paper.state !== "ok" ? sourceState(d.paper, "페이퍼 DB") : null);
    put(cutGrid, cutsOf(d).map((c) => {
      const rows = (d.cuts || {})[c.id] || [];
      const head = h("div", {class: "lbm-rh", "aria-hidden": "true"}, h("span", null, "구분"), h("span", null, trend ? "손익 (연습)" : "5년"),
        h("span", null, "지금 (페이퍼)"), h("span", null, trend ? "표본" : "판정"));
      const list = rows.length ? h("div", {class: "lbm-rows", role: "list"}, head, rows.map((r) => cutRow(r, b)))
        : ui.empty(trend ? "이 구분의 거래가 아직 없어요" : "기준표에 이 구분이 없어요");
      const extra = c.id === "hb" && rows.length ? h("div", {class: "lbm-ringw"}, ring(rows, b)) : c.id === "side" ? sideSplit(rows) : null;
      return ui.card({title: c.ko, sub: c.sub, cls: `lbm-cut lbm-cut-${c.id}${trend ? " lbm-cut-trend" : ""}`}, extra ? h("div", {class: "lbm-wide"}, extra, list) : list);
    }));
  }

  // ---------------------------------------------------------------- 숫자 읽는 법
  function drawHow(d) {
    const b = d.band;
    if (trendOn(d)) {
      const mn = d.min_n || MIN_N;
      put(how, h("ul", {class: "lbm-howl"},
        h("li", {class: "cut"}, h("b", null, "견줄 기준이 없어요. "), `${d.band_ko || "새 규칙이라 비교할 백테스트 기준이 없어요 · 2주 뒤 검토"}. `,
          "그래서 견줄 범위 없이, 이 봇이 켜진 뒤의 거래만 그대로 보여 드려요."),
        h("li", {class: "luck"}, "거래가 적으면 운이 커요. 20번 미만은 '표본 적음'이고, 몇 번의 승패로 좋다·나쁘다를 정하지 않아요 (2주 뒤 검토에서 봐요)."),
        h("li", {class: "cut"}, "표는 거래 ", h("b", null, `${fmt.int(mn)}번`), "부터 색을 칠해요 (그 전엔 회색): 손익이 + 면 초록, − 면 빨강. 판정 말은 없어요."),
        h("li", {class: "hon"}, "'진입 때 추세 판단'은 진입할 때 상위 봉 판단 4개(V3.9 · EMA·DMI·ADX · OBV · 일목·AO) 중 진입 방향과 같은 쪽이 몇 개였는지예요 (3개 이상이어야 들어가요).")),
      h("div", {class: "lbm-tones", role: "list", "aria-label": "표 색"}, ["ok", "bad", "small"].map((k) =>
        h("span", {class: ["lbm-tone", "t-" + k], role: "listitem"}, h("i", {"aria-hidden": "true"}), TREND_TONE_KO[k]))));
      return;
    }
    if (!b) { put(how, ui.note("백테스트 기준표가 없어서 숫자를 견줄 수 없어요")); return; }
    const q20 = bandAt(b, 20).honest;
    const items = [
      b.fit != null ? ["fit", "5년 백테스트 ", h("b", null, fmt.pct(b.fit, 1, false)), "는 그 5년에 맞춰 고른 설정의 결과라 낙관적이에요 (맞춘 숫자)."] : null,
      b.honest != null ? ["hon", "2020-24년만 보고 고른 쌍둥이를 처음 보는 2025-26년에 돌리면 ", h("b", null, fmt.pct(b.honest, 1, false)),
        " 이겼어요. 이게 현실 기대예요."] : null,
      b.break_even != null ? ["be", "본전은 승률 ", h("b", null, fmt.pct(b.break_even, 1, false)), "이에요 (이기고 질 때 크기로 계산).",
        b.honest != null && b.honest < b.break_even ? " 현실 기대가 본전보다 조금 낮아요: 실제 승률이 본전선 위에 머무는지가 핵심이에요." : ""] : null,
      q20 ? ["luck", "거래가 적으면 운이 커요. 현실 승률대로라도 20번 중 이긴 횟수는 보통 ", h("b", null, `${fmt.int(q20[0])}~${fmt.int(q20[2])}번`),
        " 사이에서 흔들려요 (열에 아홉). 40번 점검 전에는 판단하지 않아요."] : null,
      ["cut", "표는 거래 ", h("b", null, `${MIN_N}번`), "부터 색을 칠해요 (그 전엔 회색). 색은 지금 승률 그대로이고, 판정은 운을 따져 본 말이에요: ",
        "빨간 줄이라도 '기대 안'이면 운으로 설명되는 정도예요. 판정 말: 표본 작음 = 10번 미만 · 기대 안 = 현실 기대와 견줘 운 범위 · ",
        "주의 = 운으로는 드문 정도로 덜 이김 · 확실히 나쁨 = 여러 줄을 함께 본 엄격한 기준. 여러 줄을 한꺼번에 보면 운만으로도 '주의'가 가끔 나와요."],
    ].filter(Boolean);
    put(how, h("ul", {class: "lbm-howl"}, items.map(([k, ...t]) => h("li", {class: k}, ...t))),
      h("div", {class: "lbm-tones", role: "list", "aria-label": "표 색"}, ["hi", "ok", "lo", "bad", "small"].map((k) =>
        h("span", {class: ["lbm-tone", "t-" + k], role: "listitem"}, h("i", {"aria-hidden": "true"}), TONE_KO[k]))));
  }

  // ---------------------------------------------------------------- the answer
  function draw() {
    const d = st.d;
    if (!d) { put(tiles, motion.shimmer(2)); put(chart, motion.shimmer(4, true)); put(cutGrid, motion.shimmer(4)); return; }
    const b = d.band;
    botWords(d);
    if (drawFresh(d)) return;
    put(srcSlot, trendOn(d) ? h("p", {class: "lbm-noband"}, ui.pill("띠 없음", "thin"), ` 기대 범위 띠가 없는 이유: ${d.band_ko || "새 규칙이라 비교할 백테스트 기준이 없어요 · 2주 뒤 검토"}`)
      : !b ? sourceState({state: d.card && d.card.state === "error" ? "error" : "missing",
        reason_ko: (d.card && d.card.reason_ko) || "백테스트 기준표(deploy/combo.live-ac.expected.json)가 없어 띠를 그릴 수 없어요"}, "기대 범위 띠") : null);
    drawTiles(d);
    const lineSig = b ? idsOf(b).map((id) => ((b.accounts || {})[id] || {}).n ?? "-").join(",") : "";
    drawChart(lineSig !== st.lineSig);
    st.lineSig = lineSig;
    if (b) drawLegend(b); else { put(legend); put(alarm); }
    drawCuts(d);
    drawHow(d);
  }
  async function load() {
    let d;
    try { d = await ctx.api(MAP_API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      // a refresh that fails keeps the last answer on screen, dimmed, with its age (never silently stale)
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(body, !!st.d);
      throw e;
    }
    if (!ctx.alive()) return;
    st.okAt = Date.now();
    put(stateSlot);
    ui.dim(body, false);
    // the same records again redraw only the clock hand and the ring (the pointer's place and the lines stay)
    const sig = JSON.stringify({...d, now_ms: 0});
    if (st.d && sig === st.sig) { drawCuts(d); return; }
    st.d = d; st.sig = sig;
    draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  if (typeof ResizeObserver === "function") {
    let w0 = 0;
    const ro = new ResizeObserver(() => { const w = chart.clientWidth; if (st.d && Math.abs(w - w0) > 8) { w0 = w; drawChart(false); } });
    ro.observe(chart);
    ctx.track(() => ro.disconnect());
  }
  return {el, set() {}};
}

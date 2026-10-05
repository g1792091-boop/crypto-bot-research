// 릴스 1:3 대결 (v4 additions, wave 1 ①; ranked.md #2): the owners' own Instagram idea (REEL_H1@5m: 5m BB(20,2) +
// MA200 with its own video exits) against its three 5m coin flips (the same exits, random entries: its yardstick), and
// the 5-year study next to it. Used on 홈 (the 5분봉 group, in place of its one-row top / bottom list) and at the top of
// #/strategies/REEL_H1.
//   reelDuel(ctx, {wide, link, lazy, scope}) -> card element with .set(board) (call it with every board) and .show(on)
//   (lazy: loads the lines only once shown; again at most every 5 minutes). scope: {every, alive} of a part of a screen
//   that can close before the screen does (the strategy detail), else ctx.
// Data: the shared board (balances, trade counts: the same numbers as the group cards), GET /api/v4/replay/sparks for
// the four balance lines on one time axis (36 points, cached), GET /api/trades?group=reel for the per-trade average at
// 1x after costs (the study's own unit: ROE / leverage = P&L / position size).
// HONESTY (CONTRACT section 1): the comparison is 참고 with refNote (never a pass or a fail before the day-30 verdict);
// the coin flips are the yardstick and are shown as a median and faint lines, never as money per account; the progress
// bar is the trade count toward the verdict's own 30-trade floor (a progress, not a grade); small samples say 표본 적음;
// the 5-year line is the study's own result (research/reel5m/RESULTS_REEL5M.md, H1 fails: 0 of 40 configurations);
// money has assume(). Nothing is drawn before two real points.
import {h, s, put, ui, fmt, derive, motion} from "../core/pb.js";
import {MIN_TRADES} from "./home-shared.js";
import {verdictTs} from "./grid-kit.js";

/** The 5-year study in one line (research/reel5m/RESULTS_REEL5M.md: before costs +0.001..+0.011 % per trade, after
 *  costs −0.12..−0.13 %, H1 0 of 40 configurations pass). tests/test_dash_more_home.py ties these words to that file. */
export const STUDY_KO = "5년 연구: 비용 전 거의 0 · 비용 뒤 거래당 −0.12% · 사전 등록 시험 40개 설정 중 0개 통과";
export const STUDY_NET = -0.0012;            // after costs, per trade, 1x (the study's unit)
const REFRESH = 300000;

/** The reel account and its three 5m coin flips from a board (null before the board has them). */
export function duelAccounts(board) {
  const rows = (board && board.accounts) || [];
  const reel = rows.find((a) => a.kind === "reel") || null;
  const flips = rows.filter(fmt.isFlip5).sort((a, b) => String(a.account_id).localeCompare(String(b.account_id)));
  return reel ? {reel, flips} : null;
}

// ---------------------------------------------------------------- small pixel pictures (crispEdges, token colours)
const R = (x, y, w, hh, c) => s("rect", {x, y, width: w, height: hh, class: c});
function pixPhone() {
  return s("svg", {class: "rd-pix", viewBox: "0 0 10 14", width: 15, height: 21, "shape-rendering": "crispEdges", "aria-hidden": "true"},
    R(1, 0, 8, 14, "pb"), R(2, 2, 6, 9, "ps"), R(3, 4, 1, 4, "pm"), R(5, 3, 1, 6, "pm"), R(4, 12, 2, 1, "ps"));
}
function pixCoin(k) {
  return s("svg", {class: "rd-pix coin", viewBox: "0 0 10 10", width: 13, height: 13, "shape-rendering": "crispEdges", "aria-hidden": "true",
    style: {"--k": k}}, R(3, 0, 4, 1, "cr"), R(1, 1, 8, 1, "cr"), R(0, 3, 10, 4, "cr"), R(1, 2, 8, 6, "cr"), R(1, 8, 8, 1, "cr"),
  R(3, 9, 4, 1, "cr"), R(3, 3, 4, 4, "cf"), R(4, 4, 2, 2, "cr"));
}

// ---------------------------------------------------------------- the chart (real pixel width, redrawn on resize)
function duelChart(height) {
  const box = h("div", {class: "rd-chart", style: {height: height + "px"}});
  let m = null, W = 0, drawn = false;
  function draw() {
    W = box.clientWidth;
    if (!m || W < 60) return;
    const H = height, x0 = 2, x1 = W - 10, y0 = 8, y1 = H - 18;
    const all = [0, ...m.reel, ...m.med, ...m.flips.flat()].filter((v) => v != null && Number.isFinite(v));
    let lo = Math.min(...all), hi = Math.max(...all);
    const pad = (hi - lo) * 0.08 || 0.002;
    lo -= pad; hi += pad;
    const n = m.reel.length;
    const X = (i) => x0 + (x1 - x0) * i / Math.max(1, n - 1);
    const Y = (v) => y1 - (y1 - y0) * (v - lo) / (hi - lo);
    const path = (xs) => {
      let d = "", pen = false;
      xs.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`; pen = true; });
      return d;
    };
    const lastI = (xs) => { for (let i = xs.length - 1; i >= 0; i--) if (xs[i] != null) return i; return -1; };
    const ri = lastI(m.reel), mi = lastI(m.med);
    const reelD = path(m.reel);
    const areaD = ri > 0 ? `${reelD}L${X(ri).toFixed(1)},${Y(0).toFixed(1)}L${X(m.reel.findIndex((v) => v != null)).toFixed(1)},${Y(0).toFixed(1)}Z` : "";
    const svg = s("svg", {class: "rd-svg", width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": "릴스 잔고와 5분봉 동전 봇 3개의 잔고 흐름 (시작 대비)"},
    s("line", {class: "zero", x1: x0, x2: x1, y1: Y(0).toFixed(1), y2: Y(0).toFixed(1)}),
    s("text", {class: "ax", x: x1, y: (Y(0) - 4).toFixed(1), "text-anchor": "end"}, "시작 잔고"),
    m.flips.map((f) => s("path", {class: "f", d: path(f)})),
    s("path", {class: "md", d: path(m.med)}),
    areaD ? s("path", {class: ["area", (m.reel[ri] || 0) >= 0 ? "pos" : "neg"], d: areaD}) : null,
    s("path", {class: "rglow", d: reelD}),
    s("path", {class: "r", d: reelD}),
    mi >= 0 ? s("circle", {class: "md-dot", cx: X(mi).toFixed(1), cy: Y(m.med[mi]).toFixed(1), r: 3}) : null,
    ri >= 0 ? s("circle", {class: "r-dot", cx: X(ri).toFixed(1), cy: Y(m.reel[ri]).toFixed(1), r: 4}) : null,
    s("text", {class: "ax", x: x0, y: H - 4}, fmt.mmdd(m.t0)),
    s("text", {class: "ax", x: x1, y: H - 4, "text-anchor": "end"}, "지금"));
    box.replaceChildren(svg);
    if (!drawn) { drawn = true; motion.drawIn(svg, 700); }
  }
  if (typeof ResizeObserver === "function") new ResizeObserver(() => { if (box.clientWidth !== W) draw(); }).observe(box);
  box.set = (model) => {
    m = model;
    if (!m) {
      drawn = false;
      put(box, h("div", {class: "rd-empty"}, h("span", {class: "rd-vs-pix"}, pixPhone(), h("b", null, "vs"), pixCoin(0), pixCoin(1), pixCoin(2)),
        h("b", null, "곡선 수집 전"), h("span", null, "릴스와 동전 3개의 잔고 기록이 두 점 넘게 쌓이면 선을 그립니다. 지어낸 선은 그리지 않습니다.")));
      return;
    }
    requestAnimationFrame(draw);
  };
  return box;
}

// ---------------------------------------------------------------- the card
export function reelDuel(ctx, o = {}) {
  const sc = o.scope || ctx;
  const st = {board: null, acc: null, shown: !o.lazy, at: 0, lines: null, per: null, gen: 0};
  const big = (cls) => ui.liveNum(null, {format: "pct", dec: 1, tone: true, cls: `rd-big ${cls}`, flash: true});
  const reelNum = big("me"), medNum = big("base");
  const reelSub = h("span", {class: "rd-sub num"}), medSub = h("span", {class: "rd-sub num"});
  const chart = duelChart(o.wide ? 168 : 128);
  const prog = h("i");
  const progTxt = h("span", {class: "rd-ptxt num"});
  const perLine = h("p", {class: "rd-now"});
  const refBox = h("div", {class: "rd-ref"});
  const head = h("div", {class: "rd-head"},
    h("div", {class: "rd-title"}, h("b", null, "릴스 5분 단타"), h("span", {class: "rd-x"}, "vs"), h("span", null, "5분봉 동전 봇 3개")),
    o.link ? h("a", {class: "btn-line rd-link", href: o.link.href}, o.link.text) : null);
  const versus = h("div", {class: "rd-versus"},
    h("div", {class: "rd-side me"}, h("span", {class: "rd-who"}, pixPhone(), "릴스 (1계좌)"), reelNum, reelSub),
    h("span", {class: "rd-vs", "aria-hidden": "true"}, "VS"),
    h("div", {class: "rd-side base"}, h("span", {class: "rd-who"}, h("span", {class: "rd-coins"}, pixCoin(0), pixCoin(1), pixCoin(2)), "동전 3개 중앙값"),
      medNum, medSub));
  const legend = h("div", {class: "rd-legend"},
    h("span", {class: "me"}, h("i"), "릴스"), h("span", {class: "md"}, h("i"), "동전 3개 중앙값"), h("span", {class: "f"}, h("i"), "동전 하나하나 (흐리게)"));
  const progress = h("div", {class: "rd-prog"},
    h("div", {class: "rd-prow"}, h("span", {class: "k"}, "판정까지 릴스 거래"), progTxt),
    h("div", {class: "prog", role: "progressbar", "aria-label": `판정에 필요한 거래 ${MIN_TRADES}건 중`, "aria-valuemin": "0", "aria-valuemax": String(MIN_TRADES)}, prog),
    h("span", {class: "rd-pnote"}, `${MIN_TRADES}건이 안 되면 판정 날 '보류' · 진행 상황일 뿐 판정 아님`));
  const study = h("div", {class: "rd-study"},
    h("div", {class: "rd-srow"}, h("span", {class: "rd-chip"}, "연구 기록"), h("span", {class: "muted"}, "미리 등록한 시험 · 5분봉 2020~2026 · 거래 4만 5천여 건 · 1배 기준")),
    h("p", {class: "rd-sline"}, STUDY_KO), perLine);
  const el = ui.card({plate: "1:3 대결", cls: o.wide ? "rd-card wide" : "rd-card", label: "릴스 1:3 대결",
    acts: [ui.pill("", "ref")]}, head, versus, chart, legend, progress, study, refBox,
  ui.assume("closed", "수익률·잔고는 닫힌 거래 기준 · 선은 5분마다 기록된 평가금(열린 포지션 포함)"));

  function numbers() {
    const b = st.board, x = st.acc;
    if (!b || !x) return;
    const init = b.initial || 5000;
    const w = (a) => (a.wallet == null ? init : a.wallet);
    reelNum.update(w(x.reel) / init - 1);
    reelSub.textContent = `잔고 ${fmt.money(w(x.reel))} · 거래 ${fmt.int(x.reel.trades || 0)}건`;
    const mw = derive.median(x.flips.map(w));
    medNum.update(mw == null ? null : mw / init - 1);
    medSub.textContent = x.flips.length ? `거래 ${fmt.int(x.flips.reduce((t, a) => t + (a.trades || 0), 0))}건 (${fmt.int(x.flips.length)}개 합)` : "동전 봇 없음";
    const n = x.reel.trades || 0;
    prog.style.setProperty("--p", Math.min(100, n / MIN_TRADES * 100) + "%");
    prog.parentNode.setAttribute("aria-valuenow", String(Math.min(n, MIN_TRADES)));
    put(progTxt, h("b", null, fmt.int(n)), ` / ${MIN_TRADES}건`, n >= MIN_TRADES ? " · 채움" : "");
    const vt = verdictTs();
    put(refBox, ui.refNote(vt, "릴스는 1계좌라 흔들림이 큽니다."));
    perTrade();
  }

  // the per-trade average at 1x after costs: the study's unit, so 'now' and '5 years' read on one scale
  function perTrade() {
    const p = st.per, x = st.acc;
    if (!p || !x) { put(perLine, h("span", {class: "muted"}, "지금 거래당 평균은 거래 기록을 읽은 뒤 보입니다.")); return; }
    const pick = (ids) => {
      const xs = p.rows.filter((t) => ids.has(t.account_id) && Number(t.leverage) > 0 && Number.isFinite(Number(t.roe)))
        .map((t) => Number(t.roe) / Number(t.leverage));
      return {n: xs.length, avg: xs.length ? xs.reduce((a, v) => a + v, 0) / xs.length : null};
    };
    const r = pick(new Set([x.reel.account_id])), f = pick(new Set(x.flips.map((a) => a.account_id)));
    const cut = p.full ? "" : `최근 ${fmt.int(p.rows.length)}건 기준 · `;
    put(perLine, h("span", {class: "k"}, "지금 거래당 평균 (1배 환산 · 비용 뒤): "),
      h("span", {class: "me"}, "릴스 ", h("b", {class: ["num", fmt.tone(r.avg, fmt.pct(r.avg, 2))]}, r.avg == null ? "—" : fmt.pct(r.avg, 2)), ` (${fmt.int(r.n)}건)`),
      " · ", h("span", null, "동전 3개 ", h("b", {class: ["num", fmt.tone(f.avg, fmt.pct(f.avg, 2))]}, f.avg == null ? "—" : fmt.pct(f.avg, 2)), ` (${fmt.int(f.n)}건)`),
      " ", ui.smallSample(r.n, MIN_TRADES), cut ? h("span", {class: "muted"}, ` ${cut}`) : null);
  }

  async function load(force) {
    const x = st.acc;
    if (!x || !st.shown || !sc.alive()) return;
    if (!force && Date.now() - st.at < REFRESH) return;
    st.at = Date.now();
    const g = ++st.gen;
    const ids = [x.reel, ...x.flips].map((a) => a.account_id);
    const [sp, tr] = await Promise.all([
      ctx.api(`/api/v4/replay/sparks?ids=${encodeURIComponent(ids.join(","))}`).catch(() => null),
      ctx.api("/api/trades?group=reel&limit=600").catch(() => null)]);
    if (g !== st.gen || !sc.alive()) return;
    if (Array.isArray(tr)) {
      const total = [x.reel, ...x.flips].reduce((t, a) => t + (a.trades || 0), 0);
      st.per = {rows: tr, full: tr.length < 600 || tr.length >= total};
    }
    const init = (sp && sp.initial) || (st.board && st.board.initial) || 5000;
    const ser = (sp && sp.series) || {};
    const r = (id) => (ser[id] || []).map((v) => (v == null ? null : v / init - 1));
    const reel = r(x.reel.account_id);
    const flips = x.flips.map((a) => r(a.account_id));
    const med = reel.map((_v, i) => derive.median(flips.map((f) => f[i])));
    const real = reel.filter((v) => v != null).length;
    chart.set(real >= 2 && sp ? {t0: sp.t0, reel, flips, med} : null);
    perTrade();
  }

  el.set = (board) => {
    st.board = board;
    const was = st.acc && st.acc.reel.account_id;
    st.acc = duelAccounts(board);
    if (!st.acc) { chart.set(null); return; }          // no reel account (yet): the designed empty chart
    numbers();
    load(was !== st.acc.reel.account_id);
  };
  el.show = (on) => { st.shown = !!on; if (on) load(false); };
  chart.set(null);
  sc.every(REFRESH, () => load(true), {now: false});
  return el;
}

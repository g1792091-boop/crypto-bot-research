// 터미널 수익 차트 (기존 36, realized): the terminal's right column, rebuilt by term-plus (owners' review 10/06: "첫 며칠은 직선 하나라
// 폭락처럼 보임. 시간 단위로 그리고 승·패, 최대 낙폭도 표시"). Same panel as before (누적 선, 일별 막대, 오늘 수익, 수익 캘린더), but:
//   - the line is drawn from the closed trades of each HOUR (/api/v4/termpnl, dash/more/termpnl.py): per hour for the first 3 days,
//     per 4 hours up to 14 days, then per day, with real time ticks ("09:00 · 15:00 · 지금") instead of "10/06 … 10/06";
//   - the head line says "74승 50패 · 최대 낙폭 −1,240 USDT (참고)" (the deepest fall of the realized line from its earlier top);
//   - 24시간 / 7일 / 30일 / 전체 buttons (only the ones shorter than what there is to show; remembered per device);
//   - 오늘 수익 comes from the same hourly rows (so the line and its number can never disagree); the 수익 캘린더 is the 흐름 screen's
//     /api/v4/flow/calendar as before.
// HONESTY (CONTRACT §1): realized money of closed trades only (the open positions' P&L is in the table), the 36 only, 참고 (a running record,
// not a verdict). Loading is a shimmer, a failed load says 불러오지 못함 (with the age of the last good data and a retry that really runs:
// terminal-state.js), a real "nothing closed yet" says so; none of the three is ever drawn as a flat line or a 0. An hour without a
// closed trade is flat because nothing closed; the last point is now.
import {h, s, put, ui, fmt, motion, local, serverNow} from "../core/pb.js";
import {CAL_API} from "./flow-cal.js";
import {panel} from "./terminal-kit.js";
import {failNote, retrier} from "./terminal-state.js";
import {series, windowsFor, timeTicks, H} from "./terminal-pnl-calc.js";

const WD = ["월", "화", "수", "목", "금", "토", "일"];
const K = "core";                                     // the calendar answer's key of 기존 36
const CURVE_API = "/api/v4/termpnl";
let UID = 0;
/** 1,234.5 -> "1.2K", 356 -> "356", -7,512 -> "−7.5K" (calendar cells, axis labels). */
export const short = (v) => {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  const a = Math.abs(v);
  return a >= 1e6 ? `${fmt.num(v / 1e6, 1)}M` : a >= 1e4 ? `${fmt.num(v / 1e3, 0)}K` : a >= 1e3 ? `${fmt.num(v / 1e3, 1)}K` : fmt.num(v, 0);
};

/** pnlPanel(ctx) -> {el, onBoard} */
export function pnlPanel(ctx) {
  const st = {cal: null, calState: "loading", calAt: 0, curve: null, curveState: "loading", curveAt: 0, win: local.get("term-pnl-win", "all")};
  const big = h("b", {class: "num term-pbig"}, "—"), unit = h("span", {class: "term-punit"}, "USDT");
  const meta = h("span", {class: "term-pmeta"}, "");
  const segBox = h("div", {class: "term-pseg"});
  const chartBox = h("div", {class: "term-pchart"});
  const todayV = h("b", {class: "num term-tdv"}, "—"), todayK = h("span", {class: "term-tdk"}, "");
  const calMonth = h("span", {class: "term-calm num"}, "");
  const calBox = h("div", {class: "term-cal"});
  const legend = h("div", {class: "term-plg", title: "선 = 누적 실현 수익 · 막대 = 그 시간(또는 그날) 실현 수익"}, h("span", null, h("i", {class: "k-line", "aria-hidden": "true"}), "누적"),
    h("span", null, h("i", {class: "k-bar", "aria-hidden": "true"}), "구간별"));
  // the note and the money caption: the ⓘ (the 참고 pill stays in sight) and the terminal's one footer line
  const el = panel("수익 차트", {cls: "term-pnl", acts: [legend, ui.pill("", "ref")],
    info: `기존 36 계좌가 닫은 거래의 실현 손익 합 (열린 포지션 빼고, 아래 표에 따로) · ${ui.ASSUME_KO} · 한국 시간 · 선은 1시간(처음 3일)·4시간·하루 단위 · `
      + "최대 낙폭 = 이 선이 그 전 최고점에서 가장 깊게 내려간 만큼 · 중간 기록일 뿐 판정이 아닙니다"},
    h("div", {class: "term-phero"}, segBox, h("span", {class: "term-pnum"}, big, unit)),
    meta,
    chartBox,
    h("div", {class: "term-today"}, h("span", {class: "term-tdt"}, "오늘 수익"), todayK, h("span", {class: "grow"}), todayV, h("span", {class: "term-punit"}, "USDT")),
    h("div", {class: "term-calh"}, h("span", {class: "term-calt"}, "수익 캘린더"), calMonth, h("span", {class: "grow"}),
      h("a", {class: "term-more", href: ctx.href("flow")}, "흐름 →")),
    calBox);

  // ---------------------------------------------------------------- the curve (hourly)
  const curveReady = () => st.curve && st.curve.ready !== false;
  const spanMs = () => (st.curve ? Number(st.curve.now) - Math.max(Number(st.curve.start) || 0, Number(st.curve.from) || 0) : 0);
  const winOf = (opts) => opts.find((w) => w.id === st.win) || opts[opts.length - 1];

  function drawSeg(opts) {
    const sig = opts.map((o) => o.id).join("|") + ":" + st.win;
    if (segBox.dataset.sig === sig) return;
    segBox.dataset.sig = sig;
    if (opts.length < 2) { put(segBox, h("span", {class: "term-pwin", title: "선의 점은 1시간마다 (처음 3일), 그 뒤 4시간마다, 2주가 지나면 하루마다"},
      st.curve ? `${fmt.dur(Math.max(0, spanMs()) / 1000)}째 · ${spanMs() <= 3 * 86400000 ? "1시간마다" : spanMs() <= 14 * 86400000 ? "4시간마다" : "하루마다"}` : "기존 36 · 실현")); return; }
    const w = winOf(opts);
    put(segBox, ui.seg(opts.map((o) => ({id: o.id, label: o.ko})), w.id, (id) => { st.win = id; local.set("term-pnl-win", id); draw(); }, {label: "수익 차트 기간"}));
  }

  function chart(sr, d) {
    const W = Math.max(200, chartBox.clientWidth || 280), Hh = Math.max(96, chartBox.clientHeight || 130);
    if (sr.empty) return h("div", {class: "term-pnone"}, h("b", null, "아직 닫힌 거래 없음"), h("span", null, "기존 36의 첫 거래가 닫히면 그려집니다 (불러오기는 됐습니다)"));
    const bh = Math.round(Hh * 0.28), lh = Hh - bh - 18;                       // line area, bars area, time labels
    const pad = (sr.hi - sr.lo) * 0.1 || 1, lo = sr.lo - pad, hi = sr.hi + pad;
    const pw = W - 50, ta = sr.x0, tb = sr.x1;
    const X = (t) => 4 + ((t - ta) / Math.max(1, tb - ta)) * pw, Y = (v) => 4 + (1 - (v - lo) / (hi - lo)) * (lh - 8);
    const dd = sr.pts.map(([t, v], i) => `${i ? "L" : "M"}${X(t).toFixed(1)},${Y(v).toFixed(1)}`).join("");
    const end = sr.pts[sr.pts.length - 1], up = end[1] >= 0, id = "tg" + ++UID;
    const kids = [
      s("defs", null, s("linearGradient", {id, x1: 0, y1: 0, x2: 0, y2: 1}, s("stop", {offset: "0%", class: up ? "g-up" : "g-dn"}), s("stop", {offset: "100%", class: "g-0"}))),
      s("line", {class: "zero", x1: 0, x2: pw + 4, y1: Y(0).toFixed(1), y2: Y(0).toFixed(1)}),
      s("path", {class: "area", d: `${dd}L${X(tb).toFixed(1)},${Y(0).toFixed(1)}L${X(ta).toFixed(1)},${Y(0).toFixed(1)}Z`, fill: `url(#${id})`}),
      s("path", {class: ["ln", up ? "up" : "dn"], d: dd}),
      s("circle", {class: ["glow", up ? "up" : "dn"], cx: X(end[0]).toFixed(1), cy: Y(end[1]).toFixed(1), r: 6}),
      s("circle", {class: ["end", up ? "up" : "dn"], cx: X(end[0]).toFixed(1), cy: Y(end[1]).toFixed(1), r: 2.6}),
      s("text", {class: "ax", x: W - 42, y: Y(sr.hi) + 9}, short(sr.hi)),
      short(sr.lo) !== short(sr.hi) ? s("text", {class: "ax", x: W - 42, y: Y(sr.lo)}, short(sr.lo)) : null,
      // the "0" label only where it does not sit on top of the high or low label (a line that ends close to zero)
      sr.hi > 0 && sr.lo < 0 && Math.abs(Y(0) + 4 - (Y(sr.hi) + 9)) >= 12 && Math.abs(Y(0) + 4 - Y(sr.lo)) >= 12 ? s("text", {class: "ax", x: W - 42, y: Y(0) + 4}, "0") : null,
    ].filter(Boolean);
    // the bars: each bucket's realized P&L, centred on its time span; a hover rect over each carries the numbers
    const mx = Math.max(1, ...sr.bars.map((x) => Math.abs(x.pnl)));
    const base = lh + bh / 2;
    kids.push(s("line", {class: "zero", x1: 0, x2: pw + 4, y1: base, y2: base}));
    const col = Math.max(2, (pw / Math.max(1, (tb - ta) / sr.step)));
    for (const b of sr.bars) {
      const hgt = Math.max(1, (Math.abs(b.pnl) / mx) * (bh / 2 - 2)), cx = (X(b.t0) + X(b.t1)) / 2, bw = Math.max(2, Math.min(16, col - 1.5));
      const span = sr.step >= 24 * H ? fmt.date(b.t1 - 1) : `${fmt.kst(b.t0)} ~ ${fmt.hm(b.t1)}`;
      const tip = `${span} 실현 ${fmt.money(b.pnl, true)} USDT · 거래 ${fmt.int(b.n)} · 이김 ${fmt.int(b.w)} · 짐 ${fmt.int(b.l)} · 그때까지 누적 ${fmt.money(b.cum, true)} USDT`;
      kids.push(s("rect", {class: ["bar", b.pnl > 0 ? "up" : b.pnl < 0 ? "dn" : ""], x: (cx - bw / 2).toFixed(1), y: (b.pnl > 0 ? base - hgt : base).toFixed(1), width: bw.toFixed(1), height: hgt.toFixed(1)}),
        s("rect", {class: "hov", x: (cx - Math.max(bw, col) / 2).toFixed(1), y: 0, width: Math.max(bw, col).toFixed(1), height: lh + bh, fill: "transparent"}, s("title", null, tip)));
    }
    // time ticks: real clock times while the run is young, dates later; the left edge says where the line starts, the right "지금"
    const leftLab = tb - ta > 3 * 86400000 ? fmt.mmdd(ta) : fmt.kst(ta);
    const minX = 4 + leftLab.length * 7 + 14, maxX = pw + 4 - 46;                // never over the left label or "지금"
    const ticks = timeTicks(ta, tb, Math.max(2, Math.floor(pw / 70)), fmt.hm, fmt.mmdd).filter((k) => X(k.t) >= minX && X(k.t) <= maxX);
    for (const k of ticks) {
      kids.push(s("line", {class: "tk", x1: X(k.t).toFixed(1), x2: X(k.t).toFixed(1), y1: lh + bh, y2: lh + bh + 3}),
        s("text", {class: "ax mid", x: X(k.t).toFixed(1), y: Hh - 3}, k.label));
    }
    kids.push(s("text", {class: "ax", x: 4, y: Hh - 3}, leftLab), s("text", {class: "ax end now", x: pw + 4, y: Hh - 3}, "지금"));
    return s("svg", {class: "term-psvg", viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img",
      "aria-label": `기존 36 실현 손익 누적 ${fmt.money(end[1], true)} USDT, ${fmt.int(sr.wins)}승 ${fmt.int(sr.losses)}패, 최대 낙폭 ${fmt.money(sr.mdd)} USDT`}, kids);
  }

  function drawCurve() {
    const ok = curveReady();
    if (!ok) {
      drawSeg([]);
      motion.countTo(big, null, {dec: 2, sign: true, tone: true, glow: true});
      meta.textContent = "";
      todayV.textContent = "—"; todayK.textContent = st.curveState === "failed" ? "불러오지 못함" : st.curveState === "loading" ? "불러오는 중" : "";
      if (st.curveState === "loading") put(chartBox, motion.shimmer(3));
      else if (st.curveState === "failed") put(chartBox, failNote("수익 곡선 (닫힌 거래)", {retry: () => { st.curveState = "loading"; drawCurve(); loadCurve(); }, since: st.curveAt || null}));
      else put(chartBox, h("div", {class: "term-pnone"}, h("b", null, "계좌가 아직 없음"), h("span", null, "계좌가 만들어지고 거래가 닫히면 그려집니다")));
      return;
    }
    const opts = windowsFor(spanMs());
    drawSeg(opts);
    const w = winOf(opts), sr = series(st.curve, w.ms);
    motion.countTo(big, sr.empty ? 0 : sr.total, {dec: 2, sign: true, tone: true, glow: true});
    const stale = st.curveState === "failed";
    meta.replaceChildren(...[
      h("span", null, `기존 36 · ${w.ms ? `최근 ${w.ko} · ` : Number(st.curve.seasons) > 1 ? "이번 판정 구간 · " : ""}`),      // (after the first verdict the whole line is only the current season)
      sr.empty ? h("span", null, "아직 닫힌 거래 없음") : h("span", null, `거래 ${fmt.int(sr.trades)} · `, h("b", {class: "up"}, `${fmt.int(sr.wins)}승`), " ", h("b", {class: "down"}, `${fmt.int(sr.losses)}패`)),
      sr.empty ? null : h("span", {title: "실현 손익 선이 그 전 최고점(시작점 0 포함)에서 가장 깊게 내려간 만큼 · 닫힌 거래 기준이고 열린 포지션의 평가손익은 빠짐 · 참고"},
        ` · 최대 낙폭 ${sr.mdd > 0 ? "−" : ""}${fmt.money(sr.mdd)} USDT (참고)`),
      stale ? h("span", {class: "down"}, ` · 새로 받지 못함 (${fmt.ago(st.curveAt, serverNow())} 자료)`) : null].filter(Boolean));
    // 오늘 수익: the same hourly rows since 00:00 KST (the line and its number cannot disagree)
    const t0 = fmt.kstMidnight(serverNow());
    let n = 0, wn = 0, ls = 0, pnl = 0;
    for (const r of st.curve.hours || []) if (Number(r[0]) > t0) { pnl += Number(r[1]) || 0; n += Number(r[2]) || 0; wn += Number(r[3]) || 0; ls += Number(r[4]) || 0; }
    motion.countTo(todayV, pnl, {dec: 2, sign: true, tone: true});
    todayK.textContent = n ? `거래 ${fmt.int(n)} · ${fmt.int(wn)}승 ${fmt.int(ls)}패` : "오늘 닫힌 거래 없음";
    todayK.title = todayK.textContent;                          // (a narrow column cuts it with …: the tooltip has all of it)
    put(chartBox, chart(sr, st.curve));
  }

  // ---------------------------------------------------------------- the calendar (as 흐름 draws it)
  const daysOf = (cal) => (cal && cal.ready ? cal.days || [] : []);
  const hasDay = (d) => (d.state === "done" || d.state === "today") && d.g && d.g[K];
  function calendar(cal) {
    const days = daysOf(cal);
    if (!days.length) return [h("div", {class: "term-pnone sm"}, h("b", null, "달력에 기록된 날이 아직 없음"))];
    const vs = days.filter(hasDay).map((d) => Math.abs(Number(d.g[K].pnl) || 0)).sort((a, b) => a - b);
    const sc = vs.length ? Math.max(1, vs[Math.min(vs.length - 1, Math.floor(vs.length * 0.9))]) : 1;
    const cells = WD.map((w, i) => h("span", {class: ["term-cw", i >= 5 ? "we" : ""]}, w));
    for (let i = 0; i < days[0].dow; i++) cells.push(h("span", {class: "term-cc pad", "aria-hidden": "true"}));
    for (const d of days) {
      const has = hasDay(d), v = has ? Number(d.g[K].pnl) || 0 : null, zero = !has || Math.abs(v) < 0.5;
      const a = zero ? 0 : 0.2 + 0.55 * Math.min(1, Math.abs(v) / sc);
      const lab = `${fmt.date(d.ts)} · ${d.state === "future" ? "아직 오지 않은 날" : !has ? "기록 없음"
        : `기존 36 실현 ${fmt.money(v, true)} USDT · 거래 ${fmt.int(d.g[K].trades)} · 이김 ${fmt.int(d.g[K].wins)}`}`;
      cells.push(h("span", {class: ["term-cc", "s-" + d.state, has ? (zero ? "flat" : v > 0 ? "up" : "down") : ""], style: {"--a": a.toFixed(3)}, title: lab, "aria-label": lab},
        h("span", {class: "dn num"}, String(Number(d.d.slice(8, 10)))), has ? h("span", {class: "dv num"}, zero ? "0" : short(v)) : null));
    }
    return cells;
  }
  function drawCal() {
    const all = daysOf(st.cal);
    calMonth.textContent = all.length ? `${all[0].d.slice(0, 7).replace("-", ".")}${all[all.length - 1].d.slice(0, 7) !== all[0].d.slice(0, 7) ? ` – ${Number(all[all.length - 1].d.slice(5, 7))}월` : ""}` : "";
    if (!st.cal) {
      put(calBox, st.calState === "failed" ? failNote("수익 캘린더", {retry: () => { st.calState = "loading"; drawCal(); loadCal(); }}) : motion.shimmer(2));
      return;
    }
    put(calBox, calendar(st.cal));
  }

  const draw = () => { drawCurve(); drawCal(); };

  // ---------------------------------------------------------------- loading (each part on its own, retried by a timer that really runs)
  async function loadCurve() {
    try { const d = await ctx.api(CURVE_API); if (!ctx.alive()) return; st.curve = d; st.curveState = "ok"; st.curveAt = Date.now(); curveRetry.ok(); }
    catch (e) {
      if (e && e.name === "AbortError") return;
      st.curveState = "failed"; curveRetry.fail();             // (an older answer, if any, stays drawn with 새로 받지 못함)
    }
    if (ctx.alive()) drawCurve();
  }
  async function loadCal() {
    try { const c = await ctx.api(CAL_API); if (!ctx.alive()) return; st.cal = c; st.calState = "ok"; calRetry.ok(); }
    catch (e) {
      if (e && e.name === "AbortError") return;
      st.calState = "failed"; calRetry.fail();
    }
    if (ctx.alive()) drawCal();
  }
  const curveRetry = retrier(ctx, loadCurve), calRetry = retrier(ctx, loadCal);
  ctx.every(120000, loadCurve, {now: true});
  ctx.every(300000, loadCal, {now: true});
  // a real closed trade moves the line: ask again shortly (the server's own answer is cached 30 s)
  let tt = null;
  ctx.on("trades", () => { clearTimeout(tt); tt = setTimeout(() => ctx.alive() && loadCurve(), 3000); });
  ctx.track(() => clearTimeout(tt));
  if (typeof ResizeObserver === "function") {
    let w = 0, hh = 0;
    const ro = new ResizeObserver(() => {
      const nw = chartBox.clientWidth, nh = chartBox.clientHeight;
      if ((Math.abs(nw - w) > 4 || Math.abs(nh - hh) > 4) && curveReady()) { w = nw; hh = nh; drawCurve(); }
    });
    ro.observe(chartBox); ctx.track(() => ro.disconnect());
  }
  drawCurve(); drawCal();
  return {el, onBoard() {}};
}

// 그림자 리그: the cumulative-return chart (core/lwc.js makeChart). The member's trades added one by one (net % per trade, 1x,
// after the study's costs) against its coin-flip clones: the median of 50 clone worlds and their 10-90 % band (world k = the
// k-th clone of every trade, the clones enter at a random bar within ±5 days with the same coin, timeframe, side, stop and
// target distance). Every number comes from the server; the chart only draws it.
// HONESTY: needs two points to be a line, else it says how many closed trades are missing (never an empty frame that looks
// like 0); trades whose clones are still waiting are counted and named, not dropped silently; 참고용, 판정 아님.
import {h, put, ui, fmt, makeChart, tok} from "../core/pb.js";
import {LABEL, pctB, unavailableCard} from "./league-kit.js";

const sec = (ms) => Math.floor(Number(ms) / 1000);

/** [{time (s), value}] strictly increasing (the same second keeps the later point: two trades closing on one bar). */
export function lineData(points, pick) {
  const out = [];
  for (const p of points || []) {
    const v = pick(p);
    if (p.ms == null && p.day_ms == null) continue;
    if (v == null || !Number.isFinite(Number(v))) continue;
    const time = sec(p.ms != null ? p.ms : p.day_ms);
    if (out.length && out[out.length - 1].time === time) out[out.length - 1].value = Number(v);
    else if (!out.length || time > out[out.length - 1].time) out.push({time, value: Number(v)});
  }
  return out;
}

/** The colour with an alpha, from any CSS colour (lightweight-charts wants rgb() or hex, never a var() or an hsl()). */
export function withAlpha(color, a) {
  try {
    const cv = document.createElement("canvas");
    cv.width = cv.height = 1;
    const g = cv.getContext("2d");
    g.fillStyle = color;
    g.fillRect(0, 0, 1, 1);
    const [r, gr, b] = g.getImageData(0, 0, 1, 1).data;
    return `rgba(${r}, ${gr}, ${b}, ${a})`;
  } catch (e) { return color; }
}

const POSITION_KO = {
  inside: "지금은 띠 안에 있어요: 무작위로 들어간 것과 구별되지 않는 정도예요.",
  above: "지금은 띠 위쪽이에요. 거래가 적을 때는 운으로도 이렇게 나올 수 있어요.",
  below: "지금은 띠 아래쪽이에요. 거래가 적을 때는 운으로도 이렇게 나올 수 있어요.",
};

export function curveCard(ctx, m, d) {
  const pt = m.per_trade;
  if (pt.state !== "ok") return unavailableCard("누적 수익 곡선", pt);
  const need = d.min_trades || 30;
  const pts = pt.points || [];
  const last = pts[pts.length - 1];
  const box = h("div", {class: "lg-chart", role: "img", "aria-label": "이 멤버의 누적 수익과 동전 던지기 띠"});
  const legend = h("div", {class: "lg-legend"},
    h("span", null, h("i", {class: "lg-sw me"}), "이 멤버"), h("span", null, h("i", {class: "lg-sw flip"}), "동전 던지기 중앙값"),
    h("span", null, h("i", {class: "lg-sw band"}), "동전 던지기 10~90% 띠"));
  const read = last ? h("p", {class: "lg-read"},
    `거래 ${fmt.int(last.n)}건째까지 · 이 멤버 `, pctB(last.member_cum_pct), " · 동전 중앙값 ", pctB(last.flip_p50),
    ` · 띠 ${fmt.pctOf(last.flip_p10, 2, true)} ~ ${fmt.pctOf(last.flip_p90, 2, true)}`, h("br"), pt.position ? POSITION_KO[pt.position] : null,
    " ", ui.smallSample(pt.n, need)) : null;
  const card = ui.card({plate: "누적 수익 곡선", sub: "거래 1회당 %를 더함 · 1배 · 비용 뒤", cls: "lg-curve", label: "누적 수익 곡선", acts: [ui.pill(LABEL, "thin")]},
    pts.length >= 2 ? box : h("p", {class: "lg-empty"}, ui.notYet("선 그리기 전"),
      ` 동전 던지기까지 모두 끝난 닫힌 거래가 2건 이상 있어야 선이 그려져요. 지금은 ${fmt.int(pt.n)}건이에요.`),
    pts.length >= 2 ? legend : null, read,
    pt.awaiting_clones ? h("p", {class: "lg-sub"}, `동전 던지기 쪽이 아직 다 안 끝난 거래 ${fmt.int(pt.awaiting_clones)}건은 곡선에 들어오지 않았어요(동전은 최대 5일 뒤에 들어가는 것까지 끝나야 해요). 그래서 곡선은 며칠 늦게 따라와요.`) : null,
    pt.thinned ? h("p", {class: "lg-sub"}, "점이 많아서 일부만 그렸어요(마지막 점은 그대로예요).") : null,
    ui.note(pt.note_ko || "", " 띠 안이면 '무작위로 들어간 것과 구별되지 않는다'는 뜻이에요. 합격·불합격을 정하는 비교가 아니에요."));

  card.draw = async () => {
    if (pts.length < 2) return;
    let C;
    try {
      C = await makeChart(box, {grid: {vertLines: {visible: false}, horzLines: {visible: false}}, rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.1, bottom: 0.1}},
        timeScale: {rightOffset: 2}});
    } catch (e) { if (ctx.alive()) put(box, ui.errorBox(e, () => card.draw())); return; }
    if (!ctx.alive()) { C.dispose(); return; }
    ctx.track(C.dispose);
    const me = tok("--cmp-hi"), flip = tok("--cmp-lo"), face = tok("--surface");
    const fmtY = {type: "custom", minMove: 0.01, formatter: (v) => fmt.pctOf(v, 2, true)};
    const quiet = {lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, priceFormat: fmtY};
    const edge = withAlpha(flip, 0.5), fill = withAlpha(flip, 0.26);
    // the band: the 90 % line filled down in the band colour, then the 10 % line filled down in the chart's own face colour
    const top = C.chart.addAreaSeries({...quiet, topColor: fill, bottomColor: fill, lineColor: edge, lineWidth: 1});
    const low = C.chart.addAreaSeries({...quiet, topColor: face, bottomColor: face, lineColor: edge, lineWidth: 1});
    const mid = C.chart.addLineSeries({...quiet, color: flip, lineWidth: 2, lineStyle: 2});
    const mine = C.chart.addLineSeries({...quiet, color: me, lineWidth: 2, crosshairMarkerVisible: true, crosshairMarkerRadius: 3, priceFormat: fmtY});
    top.setData(lineData(pts, (p) => p.flip_p90));
    low.setData(lineData(pts, (p) => p.flip_p10));
    mid.setData(lineData(pts, (p) => p.flip_p50));
    mine.setData(lineData(pts, (p) => p.member_cum_pct));
    mine.createPriceLine({price: 0, color: tok("--line-2"), lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: ""});
    C.chart.timeScale().fitContent();
  };
  return card;
}

// 그림자 리그: the owners'-style virtual account (5,000 USDT, 20 % margin x 20x, one position at a time, a 4.5 % adverse move
// liquidates), per timeframe and over all four together, with its deepest fall (최대 낙폭). Day-end realized equity as the agents
// stored it (closed trades only, an open position is not marked); the page only draws the stored rows.
// HONESTY: the account is a calculation, not a paper account (no money, no orders); a scope with no closed trade says '기록 전'
// instead of drawing the start balance as if it were a result; the 5-year study's own account result sits next to it.
import {h, put, ui, fmt, makeChart, tok, local} from "../core/pb.js";
import {LABEL, pctB, unavailableCard} from "./league-kit.js";
import {lineData} from "./league-chart.js";

const SCOPES = [{id: "all", label: "네 봉 합쳐서"}, {id: "15m", label: "15분"}, {id: "30m", label: "30분"}, {id: "1h", label: "1시간"}, {id: "4h", label: "4시간"}];
const KEY = "league-scope";

export function accountCard(ctx, m) {
  const a = m.account;
  if (a.state !== "ok") return unavailableCard("가상 계좌", a);
  let pick = local.get(KEY, "all");
  if (!SCOPES.some((s) => s.id === pick)) pick = "all";
  const study = m.study;
  const start = a.start_equity;
  const rules = `${fmt.usdt(start)}로 시작 · 증거금 ${fmt.pct(a.margin_frac, 0, false)} × ${fmt.lev(a.leverage)} · 한 번에 1개 · ${fmt.pct(a.liq_adverse, 1, false)} 거꾸로 가면 강제 청산(증거금만큼 잃음)`;
  const stats = h("div", {class: "stats lg-stats"});
  const when = h("p", {class: "lg-sub"});
  const chartBox = h("div", {class: "lg-chart short", role: "img", "aria-label": "가상 계좌의 하루 끝 잔고"});
  const empty = h("p", {class: "lg-empty"});
  let C = null, line = null;

  function paint() {
    const sc = a.scopes[pick] || {points: [], last: null};
    const L = sc.last;
    const label = (SCOPES.find((s) => s.id === pick) || SCOPES[0]).label;
    put(stats,
      ui.stat("지금 잔고", L ? fmt.usdt(L.equity) : ui.notYet("기록 전"), L ? `시작 ${fmt.usdt(start)}` : "닫힌 거래가 없어요"),
      ui.stat("수익률", L ? pctB(L.ret_pct, 2) : "—", L ? `${fmt.num(L.x, 3)}배` : null),
      ui.stat("최대 낙폭", L ? fmt.pctOf(L.max_dd_pct, 1) : "—", "고점에서 가장 많이 내려간 폭 · 하루 끝 잔고 기준"),
      ui.stat("받아들인 거래", L ? fmt.int(L.taken) : "—", "열린 거래가 있으면 다음 거래는 못 받아요"),
      ui.stat("강제 청산", L ? fmt.int(L.liquidated) : "—", `걸리면 증거금 ${fmt.pct(a.margin_frac, 0, false)}를 잃어요`));
    put(when, L ? `${label} · 기준 시각 ${fmt.kst(sc.asof_ms)} · 하루 끝 잔고 ${fmt.int(sc.points.length)}개` : `${label}: 아직 끝난 거래가 없어서 잔고를 그리지 않았어요. 시작 잔고 그대로라는 뜻이 아니라 기록이 아직 없다는 뜻이에요.`);
    const drawn = !!L && sc.points.length >= 2;
    chartBox.hidden = !drawn;
    put(empty, L && !drawn ? "하루 끝 잔고가 2개 이상 쌓이면 선이 그려져요." : null);
    empty.hidden = drawn || !L;
    if (line) line.setData(lineData(sc.points, (p) => p.equity));
    if (C && drawn) requestAnimationFrame(() => { try { C.chart.timeScale().fitContent(); } catch (e) { /* chart gone */ } });
  }
  const seg = ui.seg(SCOPES, pick, (id) => { pick = id; local.set(KEY, id); paint(); if (!C && !chartBox.hidden) draw(); }, {label: "가상 계좌 보기"});

  async function draw() {
    if (C) return;
    try { C = await makeChart(chartBox, {rightPriceScale: {borderColor: tok("--line-2"), scaleMargins: {top: 0.12, bottom: 0.1}}, timeScale: {rightOffset: 2}}); } catch (e) {
      if (ctx.alive()) put(chartBox, ui.errorBox(e, () => draw()));
      return;
    }
    if (!ctx.alive()) { C.dispose(); C = null; return; }
    ctx.track(C.dispose);
    line = C.chart.addLineSeries({color: tok("--accent"), lineWidth: 2, lastValueVisible: true, priceLineVisible: false, crosshairMarkerRadius: 3,
      priceFormat: {type: "custom", minMove: 0.01, formatter: (v) => fmt.money(v)}});
    line.createPriceLine({price: start, color: tok("--line-2"), lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "시작"});
    paint();
  }

  const card = ui.card({plate: "가상 계좌 (두 분 방식)", sub: "그렇게 했다면 어땠을지 계산한 숫자", cls: "lg-account", label: "가상 계좌", acts: [ui.pill(LABEL, "thin")]},
    seg, stats, when, chartBox, empty,
    h("p", {class: "lg-sub"}, rules),
    study && study.account_ko ? h("p", {class: "lg-vs"}, h("b", null, "5년 시험의 같은 계좌 "), study.account_ko) : null,
    ui.assume("closed", "가상 계좌: 끝난 거래만 반영, 열린 포지션은 평가하지 않음"),
    ui.note("이 계좌는 진짜 계좌도 331개 모의 계좌 중 하나도 아니에요. 같은 신호로 그렇게 들어갔다면 잔고가 어땠을지 계산한 숫자이고, 순위·판정에 들어가지 않아요. 동전 던지기 계좌와의 비교선은 따로 그리지 않았어요(위의 누적 곡선이 그 비교예요)."));
  paint();                                  // the numbers do not wait for the chart
  card.draw = () => { const sc = a.scopes[pick]; return sc && sc.points.length >= 2 ? draw() : null; };
  return card;
}

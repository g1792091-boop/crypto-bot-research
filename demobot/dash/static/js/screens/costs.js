// #/costs 실제 비용 (CONTRACT 8.3): what a market order really cost on the Binance order book when the demo lab would
// have sent it, against the engine's assumed 2 bps of slippage. Per coin the cost by order size (median, 90% and the
// last read; buy and sell), the spread and the 10,000 USD cost over time, every account line's P&L with the measured
// cost, and the private plug-ins' limit fills that only touched their price. costs.json every 60 s.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {lineChart} from "../chart.js";
import {COINS, LEVS} from "../labels.js";

const STAT_KO = {median: "중간값", p90: "비쌀 때(90%)", last: "마지막"};
const sizeKo = (s) => (Number(s) >= 1000 ? `$${fmt.num(Number(s) / 1000, 0)}k` : `$${fmt.num(s, 0)}`);
const bp = (x, dec = 2) => (fmt.bad(x) ? "—" : `${fmt.num(x, dec)}bp`);

export async function mount(el, ctx) {
  ctx.setTitle("실제 비용");
  const saved = local.get("costs", {}) || {};
  const f = {side: saved.side === "sell" ? "sell" : "buy", stat: STAT_KO[saved.stat] ? saved.stat : "median",
    coin: COINS.includes(saved.coin) ? saved.coin : "BTCUSD", lev: saved.lev || "all"};
  const keep = () => local.set("costs", f);
  const lead = h("div", {class: "stack tight"});
  const tblBox = h("div");
  const sideSeg = ui.seg([{id: "buy", label: "살 때 (롱 진입)"}, {id: "sell", label: "팔 때 (숏 진입)"}], f.side,
    (v) => { f.side = v; keep(); paintTable(); }, {label: "주문 방향"});
  const statSeg = ui.seg(Object.entries(STAT_KO).map(([id, label]) => ({id, label})), f.stat,
    (v) => { f.stat = v; keep(); paintTable(); }, {label: "어느 값"});
  const coinSeg = ui.seg(COINS.map((c) => ({id: c, label: fmt.coin(c)})), f.coin, (v) => { f.coin = v; keep(); paintChart(); }, {label: "코인", cls: "scroll"});
  const chartBox = h("div", {class: "dl-chart dl-cchart", role: "img", "aria-label": "스프레드와 1만 달러 주문 비용의 흐름"});
  const chartNote = h("p", {class: "note"});
  const levSeg = ui.seg([{id: "all", label: "전체"}, ...LEVS.map((L) => ({id: String(L), label: `${L}배`}))], f.lev,
    (v) => { f.lev = v; keep(); paintLines(false); }, {label: "배수"});
  const linePg = ui.pager({size: 20, empty: "잰 거래가 있는 줄이 없습니다", render: (part) => lineTable(part, ctx)});
  const makerBox = h("div"), notesBox = h("div");
  el.append(ui.screenHead("실제 비용", "호가창에서 잰 진짜 주문 비용"),
    ui.card({hero: true, plate: "한 줄로"}, lead),
    ui.card({plate: "코인 × 주문 크기", sub: "시장가 주문 한 번의 비용 (bp = 0.01%) · 스프레드 절반 포함", cls: "dl-controls"},
      h("div", {class: "dl-fields"}, ui.field("방향", sideSeg), ui.field("값", statSeg)), tblBox),
    ui.card({plate: "흐름", sub: "스프레드와 1만 달러 주문 비용 · 점선 = 가정 2bp"}, coinSeg, chartBox,
      h("div", {class: "dl-legend"}, h("span", {class: "dl-lg"}, h("i", {class: "dl-li-p1"}), "스프레드 (사고팔 값의 차이)"),
        h("span", {class: "dl-lg"}, h("i", {class: "dl-li-p2 dl-dash"}), "1만 달러 살 때 비용")), chartNote),
    ui.card({plate: "줄마다 실제 비용을 넣으면", sub: "잰 진입 비용 − 가정 2bp를 들어갈 때와 나갈 때 두 번 뺀 손익", acts: levSeg}, linePg.el),
    ui.card({plate: "지정가 진입 확인", sub: "비공개 매매법 · 봉이 지정가를 1bp도 못 넘은 체결 = 닿기만 함"}, makerBox),
    ui.card({plate: "알아 둘 것"}, notesBox));

  let data = null, seen = null, chart = null;
  async function load() {
    let d;
    try { d = await ctx.api("/api/costs"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!data) put(lead, ui.errorBox(e, load));
      return;
    }
    if (d && d.generated_ms != null && d.generated_ms === seen) return;
    seen = d ? d.generated_ms : null;
    data = d;
    if (isMissing(d)) {
      put(lead, ui.missing("실제 비용 자료(costs.json)"), explain(null));
      for (const b of [tblBox, chartBox, makerBox, notesBox]) put(b, ui.none("준비 중"));
      linePg.set([]);
      return;
    }
    paintLead(d);
    paintTable();
    await paintChart();
    paintLines(true);
    paintMaker(d.maker || []);
    put(notesBox, (d.notes_ko || []).length ? h("ul", {class: "dl-ul"}, d.notes_ko.map((x) => h("li", null, x))) : ui.none());
  }

  function paintLead(d) {
    const a = d.assumed_bps ?? 2;
    const i5 = (d.sizes || []).indexOf(5000), i10 = (d.sizes || []).indexOf(10000);
    const med = (c, i) => (i >= 0 && c.buy_bps && c.buy_bps.median ? c.buy_bps.median[i] : null);
    const over = (d.coins || []).filter((c) => Number(med(c, i10)) > a).map((c) => fmt.coin(c.coin));
    const cheap = (d.coins || []).filter((c) => med(c, i5) != null && Number(med(c, i5)) <= a).map((c) => fmt.coin(c.coin));
    put(lead,
      explain(a),
      h("p", {class: "dl-vline"}, over.length
        ? `1만 달러 주문이 가정(${fmt.num(a, 0)}bp)보다 비싼 코인: ${over.join(", ")}. 큰 배수에서 이 코인은 결과가 조금 나빠집니다.`
        : `1만 달러 주문까지는 모든 코인이 가정(${fmt.num(a, 0)}bp)보다 쌌습니다.`),
      cheap.length ? h("p", {class: "note"}, `5천 달러 주문이 가정보다 싼 코인: ${cheap.join(", ")}.`) : null,
      h("p", {class: "note"}, d.since_ms ? `호가 기록 시작 ${fmt.kst(d.since_ms)} · 그 전 거래는 잰 값이 없습니다.` : "호가 기록 시작 때: 기록 없음"));
  }

  function paintTable() {
    if (!data || isMissing(data)) return;
    const sizes = data.sizes || [];
    const a = Number(data.assumed_bps ?? 2);
    const key = f.side === "sell" ? "sell_bps" : "buy_bps";
    const rows = data.coins || [];
    if (!rows.length || !sizes.length) { put(tblBox, ui.none("준비 중")); return; }
    put(tblBox, ui.table([
      {label: "코인", l: true, hcls: "dl-c2", cls: "dl-c2", get: (c) => h("span", {class: "dl-kn"}, h("b", null, fmt.coin(c.coin)),
        h("small", {class: "muted"}, `스프레드 ${bp(c.spread_bps && c.spread_bps.median)}`))},
      ...sizes.map((s, i) => ({label: sizeKo(s), get: (c) => {
        const v = ((c[key] || {})[f.stat] || [])[i];
        if (v == null) return h("span", {class: "muted", title: "호가 500단계로 이 크기를 다 채우지 못함"}, "—");
        return h("span", {class: ["num", Number(v) > a ? "warn-t" : ""], title: Number(v) > a ? "가정보다 비쌈" : "가정 이하"}, fmt.num(v, 2));
      }})),
      {label: "기록 수", get: (c) => h("span", {class: "muted", title: c.last_ms ? `마지막 ${fmt.kst(c.last_ms)}` : ""}, fmt.int(c.n))},
    ], rows, {cls: "dl-costtbl"}),
    ui.note(`주황 글씨 = 가정(${fmt.num(a, 0)}bp)보다 비쌈 · — = 호가 500단계로 그 크기를 다 못 채움 · `
      + `${STAT_KO[f.stat]}: ${f.stat === "p90" ? "열 번 중 아홉 번은 이보다 쌌다는 값" : f.stat === "last" ? "가장 최근에 읽은 호가" : "읽은 값들의 가운데"}`));
  }

  async function paintChart() {
    if (!data || isMissing(data)) return;
    const s = (data.series || []).find((x) => x.coin === f.coin);
    if (!s || !(s.points || []).length) {
      if (chart) { chart.dispose(); chart = null; }
      put(chartBox, ui.none("기록 없음"));
      chartNote.textContent = "";
      return;
    }
    try {
      if (!chart) {
        put(chartBox);
        chart = await lineChart(chartBox, {format: (p) => `${fmt.num(p, 2)}bp`, base: Number(data.assumed_bps ?? 2), baseTitle: "가정"});
        ctx.signal.addEventListener("abort", () => chart && chart.dispose());
      }
      if (!ctx.alive()) return;
      chart.set([{key: "spread", title: "스프레드", token: "--pick-1", dash: 0, points: s.points, col: 1},
        {key: "buy10k", title: "1만$ 비용", token: "--pick-2", dash: 2, points: s.points, col: 2}]);
      const pts = s.points;
      chartNote.textContent = `${fmt.coin(f.coin)} · ${fmt.kst(pts[0][0])} ~ ${fmt.kst(pts[pts.length - 1][0])} · 점 ${fmt.int(pts.length)}개 (많으면 골라 줄임)`;
    } catch (e) {
      put(chartBox, ui.empty("차트를 그리지 못했습니다."));
    }
  }

  function paintLines(keepPage) {
    if (!data || isMissing(data)) return;
    let rows = (data.lines || []).slice();
    if (f.lev !== "all") rows = rows.filter((r) => String(r.L) === f.lev);
    rows.sort((x, y) => Math.abs(Number(y.pnl_adj) - Number(y.pnl)) - Math.abs(Number(x.pnl_adj) - Number(x.pnl)));
    linePg.set(rows, keepPage);
  }

  function paintMaker(rows) {
    if (!rows.length) { put(makerBox, ui.none("지정가로 들어간 계좌가 없습니다")); return; }
    put(makerBox, ui.table([
      {label: "계좌", l: true, get: (r) => h("a", {href: ctx.href("account", r.id)}, r.name || r.id)},
      {label: "배수", get: (r) => fmt.lev(r.L)},
      {label: "지정가 체결", get: (r) => fmt.int(r.n)},
      {label: "닿기만 함", get: (r) => h("span", null, fmt.int(r.touch_only), h("small", {class: "muted"}, ` (${fmt.ratio(r.touch_share)})`))},
      {label: "손익", get: (r) => ui.signed(fmt.money(r.pnl, true), fmt.tone(r.pnl, fmt.money(r.pnl)))},
      {label: "닿기만 한 것 빼면", get: (r) => ui.signed(fmt.money(r.pnl_strict, true), fmt.tone(r.pnl_strict, fmt.money(r.pnl_strict)), "b")},
    ], rows), ui.note("지정가는 가격이 거기까지 와야 체결됩니다. 봉이 그 가격에 닿기만 하고 1bp도 더 가지 않았다면, 실제로는 줄을 서 있다가 "
      + "체결이 안 됐을 수 있습니다. 오른쪽 끝 칸은 그런 체결을 모두 없었던 것으로 친 손익입니다."));
  }

  await load();
  ctx.every(60000, load);
}

function explain(a) {
  const x = a == null ? 2 : a;
  return h("p", {class: "dl-lead"}, "봇은 시장가로 들어가고 나갈 때마다 수수료 0.05%와 별도로 ", h("b", null, `${fmt.num(x, 0)}bp(${fmt.num(x / 100, 2)}%)`),
    "만큼 값이 불리하게 체결된다고 가정합니다. 실제로는 15분봉이 열린 직후 바이낸스 호가창을 읽어, 그 크기의 주문이 정말 얼마를 냈을지 잽니다. ",
    "아래 숫자가 이 가정보다 작으면 봇의 계산이 조금 보수적이고, 크면 실제로는 결과가 그만큼 나빴을 것이라는 뜻입니다. 주문 크기가 클수록 호가를 더 깊이 먹어서 비용이 커집니다.");
}

function lineTable(rows, ctx) {
  return ui.table([
    {label: "계좌", l: true, hcls: "dl-c2", cls: "dl-c2 dl-wrap2", get: (r) => h("a", {href: ctx.href("account", r.id)}, r.name || r.id)},
    {label: "배수", get: (r) => fmt.lev(r.L)},
    {label: "잰 거래", get: (r) => fmt.int(r.n)},
    {label: "평균 추가 비용", get: (r) => h("span", {class: ["num", Number(r.mean_extra_bps) > 0 ? "warn-t" : ""]}, fmt.bad(r.mean_extra_bps) ? "—" : `${fmt.num(r.mean_extra_bps, 2, true)}bp`)},
    {label: "추가 R", get: (r) => fmt.bad(r.mean_extra_R) ? "—" : fmt.num(r.mean_extra_R, 3, true) + "R"},
    {label: "손익", get: (r) => ui.signed(fmt.money(r.pnl, true), fmt.tone(r.pnl, fmt.money(r.pnl)))},
    {label: "실제 비용 넣은 손익", get: (r) => ui.signed(fmt.money(r.pnl_adj, true), fmt.tone(r.pnl_adj, fmt.money(r.pnl_adj)), "b")},
    {label: "차이", get: (r) => { const dd = Number(r.pnl_adj) - Number(r.pnl); const t = fmt.money(dd, true); return ui.signed(t, fmt.tone(dd, t)); }},
  ], rows, {cls: "dl-costlines"});
}

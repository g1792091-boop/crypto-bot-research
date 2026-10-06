// 5년 조합 시험 (combo-5y): the committed 5-year combination results (GET /api/v4/combo5y, dash/more/combo5y.py, made
// offline by paperbot/dash/tools/combo5y.py). render5y(ctx, el) draws every card into `el`; the #/combo screen imports
// it, and #/combo5y (combo5y.js) shows it on its own. Cards: 점수 높은 조합 (tap one: its 5-year monthly curve against
// its members and the coin-flip band of the same size), 다음 해에도 (walk-forward by calendar year), 5년 상관 지도
// (daily P&L correlation / worst-5%-day correlation / co-loss share, 36 x 36), 신호 합치기 (how many merged rules were
// tried and how many survive), 한 계좌로 합치면 (one shared account vs separate accounts), 어떻게 계산했나 (methods,
// parity with the research numbers, the selection-bias caveat). Backtest only: 설명용, 판정 아님; coin flips are 참고.
// Every server string is text (h()); numbers only through fmt.
import {h, s, put, ui, fmt, motion, local} from "../core/pb.js";
import {viewHead} from "./analysis-kit.js";

const API = "/api/v4/combo5y";
const FRESH_MS = 30 * 60 * 1000;
const TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"};
let cache = null;                         // {at, p}: the answer only changes when the JSON is regenerated

function ensureCss() {
  // #/combo5y's own css @imports it; any other screen gets it linked once here
  if (document.querySelector('link[data-c5], link[href$="/screens/combo5y.css"]')) return;
  document.head.append(h("link", {rel: "stylesheet", href: "/static/v4/screens/combo-5y.css", dataset: {c5: "1"}}));
}
function load(ctx) {
  if (!cache || Date.now() - cache.at > FRESH_MS) {
    const p = ctx.api(API);
    cache = {at: Date.now(), p};
    p.catch(() => { if (cache && cache.p === p) cache = null; });
  }
  return cache.p;
}
const nm = (d, sid) => (d.names && d.names[sid]) || fmt.stratKo(sid) || sid;
/** Backtest dollars (not live money): "$12,345" / "−$1,234". */
const dol = (x, sign = false) => (x == null || !Number.isFinite(Number(x)) ? "—"
  : (Number(x) < 0 ? fmt.MINUS : sign && Number(x) > 0 ? "+" : "") + "$" + fmt.num(Math.abs(Number(x)), 0));
const capCaption = () => ui.assume("closed", "5년 과거 시험(2021-08~2026-09) · 매달 계좌마다 $5,000로 새로 시작한 계산 · 실제 돈 아님");
function verdictTs(ctx) {
  const sm = ctx.store && ctx.store.get ? ctx.store.get("summary") : null;
  return (sm && sm.restart && sm.restart.ready && sm.restart.verdict_ts) || (sm && sm.next_checkpoint && sm.next_checkpoint.ts) || null;
}

/** Draw the 5-year combination cards into el (a shimmer while the answer comes). */
export async function render5y(ctx, el) {
  ensureCss();
  const root = h("div", {class: "stack c5"});
  put(el, root);
  put(root, motion.shimmer(5, true));
  let d;
  try { d = await load(ctx); } catch (e) {
    if (ctx.alive && !ctx.alive()) return;
    put(root, ui.errorBox(e, () => { cache = null; render5y(ctx, el); }));
    return;
  }
  if (ctx.alive && !ctx.alive()) return;
  if (!d || d.unavailable) {
    put(root, ui.card({plate: "5년 조합 시험"}, h("p", null, "준비 중입니다. "), h("p", {class: "muted"}, (d && d.note) || "결과 파일이 아직 없습니다.")));
    return;
  }
  const p = d.portfolio || {};
  const env = {ctx, d, vts: verdictTs(ctx), v: local.get("c5-var", "all")};
  if (!p[env.v]) env.v = "all";
  // the cards that follow the chosen search (36개 전부 / 거래가 있는 매매법만) are drawn again on a switch
  const varSlot = h("div", {class: "stack c5-varslot"});
  const drawVar = () => put(varSlot, ...[topCard(env), walkCard(env), sharedCard(env)].filter(Boolean));
  drawVar();
  const pick = variantCard(env, (id) => { env.v = id; local.set("c5-var", id); drawVar(); motion.swap(varSlot); });
  const parts = [head(env), pick, varSlot, corrCard(env), mergedCard(env), methodsCard(env)];
  put(root, ...parts.filter(Boolean));
  motion.swap(root);
}

// ---------------------------------------------------------------- which strategies the search used
function variantCard({d, v}, onPick) {
  const p = d.portfolio || {};
  const rule = p.active_rule || {};
  if (!p.active) return null;
  const left = (rule.left_out || []).map((x) => `${nm(d, x.strategy)} ${fmt.int(x.trades)}건`).join(" · ");
  return ui.card({plate: "어떤 매매법으로 찾았나", sub: "아래 조합 · 다음 해 · 한 계좌 카드가 따라 바뀝니다"},
    ui.seg([{id: "all", label: `36개 전부 (${fmt.int((p.all.units || []).length)}개)`},
      {id: "active", label: `거래가 있는 것만 (${fmt.int((p.active.units || []).length)}개)`}], v, onPick, {label: "탐색에 넣은 매매법"}),
    h("p", {class: "c5-sum"}, rule.why || ""),
    left ? h("p", {class: "an-note"}, `빠진 매매법 (5년 거래 ${fmt.int(rule.min_trades || 62)}건 미만): ${left}`) : null);
}

// ---------------------------------------------------------------- head
function head({d}) {
  const m = d.merged || {}, p = d.portfolio || {}, mt = d.methods || {};
  const nMonths = (d.months || []).length;
  return viewHead({plate: "5년 조합 시험", q: "36개 매매법을 묶었다면, 지난 5년 동안 어땠을까",
    meta: `${(d.months || [])[0] || ""} ~ ${(d.months || [])[nMonths - 1] || ""} · ${fmt.int(nMonths)}달 · 기존 36 · ${d.label || "설명용, 판정 아님"}`,
    at: d.generated ? Date.parse(d.generated) : null,
    read: "매달 1일 계좌마다 $5,000로 새로 시작한 v4 규칙 그대로의 과거 계산입니다 (지금 30일 실험과 같은 모양). 매매법 1개 = 15분·30분·1시간·4시간 계좌 4개의 합. 점수 = 5년 총손익 ÷ 최대 낙폭($).",
    warn: [h("p", {class: "an-warn"}, ui.pill("선택 편향", "warn"), " ", mt.caveat || "이 36개는 바로 이 5년 자료를 보고 고른 매매법이라 숫자가 실제보다 좋게 나오기 쉽습니다."),
      h("div", {class: "stats s4 c5-stats"},
        ui.stat("매매법", fmt.int((d.strategies || []).length), "기존 36 × 봉 4개"),
        ui.stat("조합 탐색", "2~5개", (p.search && p.search.beam) ? `2·3개 전부 + 4·5개 상위 ${fmt.int(p.search.beam)}개에서` : null),
        ui.stat("합친 규칙 시험", fmt.int(m.trials || 0), `거래 ${fmt.int(m.min_trades || 100)}건 넘은 것 ${fmt.int(m.tested || 0)}개`),
        ui.stat("두 단계 다 넘은 규칙", fmt.int(m.both_pass || 0), "우연 거르기 + 섞은 비교"))]});
}

// ---------------------------------------------------------------- top portfolios + the curve of the chosen one
function topCard({d, vts, v}) {
  const p = d.portfolio || {};
  const V = p[v] || {};
  const top = V.top || [];
  if (!top.length) return ui.card({plate: "점수 높은 조합"}, ui.empty("조합 결과가 없습니다"));
  const detail = h("div", {class: "c5-detail"});
  let sel = Math.min(Number(local.get(`c5-top-${v}`, 0)) || 0, top.length - 1);
  const list = h("div", {class: "c5-list", role: "list"});
  const rows = top.map((t, i) => {
    const r = h("button", {class: ["lrow click c5-row", i === sel ? "on" : ""], type: "button", "aria-pressed": String(i === sel),
      onclick: () => pick(i)},
    h("span", {class: "rk"}, `${fmt.int(i + 1)}위`),
    h("span", {class: "lname c5-wrap"}, t.units.map((u) => nm(d, u)).join(" + ")),
    h("span", {class: ["ret num", fmt.tone(t.mean_month, fmt.pct(t.mean_month, 1))]}, `월 ${fmt.pct(t.mean_month, 1)}`),
    h("span", {class: "meta"},
      h("span", null, `${fmt.int(t.k)}개 · 점수 ${fmt.num(t.score, 2)}`),
      h("span", null, `5년 거래 ${fmt.int(t.trades)}건`),
      t.trades != null && t.trades < 62 ? ui.pill("거의 거래 안 함", "warn") : null,
      h("span", null, `최대 낙폭 ${dol(-t.dd_usd)}`),
      h("span", null, `이긴 달 ${fmt.pct(t.win_months, 0, false)}`),
      h("span", null, `분산 효과 ${t.div == null ? "—" : fmt.num(t.div, 2)}`)));
    list.append(h("div", {role: "listitem", class: "c5-li"}, r));
    return r;
  });
  function pick(i) {
    sel = i;
    local.set(`c5-top-${v}`, i);
    rows.forEach((r, j) => { r.classList.toggle("on", j === i); r.setAttribute("aria-pressed", String(j === i)); });
    put(detail, curveBox(d, top[i]));
    motion.swap(detail);
  }
  put(detail, curveBox(d, top[sel]));
  const sh = V.shuffled_days || {}, cf = V.coin_flips || {};
  const allLose = top.every((t) => (t.pnl || 0) <= 0);
  const shWords = sh.rank_p == null ? null : sh.rank_p > 0.1
    ? "날짜를 섞은 자료에서도 이만한 점수가 자주 나옵니다: 이 조합이 특별하다고 보기 어렵습니다."
    : "날짜를 섞은 자료에서는 이만한 점수가 드뭅니다. 다만 36개 자체를 이 5년으로 골랐다는 점은 그대로입니다.";
  return ui.card({plate: "점수 높은 조합", sub: "오른쪽 = 한 달 평균 수익률 (합친 자금 대비)"},
    allLose ? h("p", {class: "c5-sum"}, h("b", null, "10개 모두 5년 동안 돈을 잃었습니다. "),
      "점수는 '덜 잃은 정도'입니다. 묶어서 돈을 번 조합은 이 규칙에서는 찾지 못했습니다.") : null,
    h("p", {class: "an-note"}, "한 줄을 누르면 그 조합의 5년 흐름을 아래에 그립니다. 점수 = 5년 손익 합계 ÷ 가장 깊은 낙폭 (−1 근처 = 거의 내리막만). 분산 효과 = 각자 가장 깊은 낙폭을 더한 것 ÷ 묶은 곡선의 가장 깊은 낙폭 (1이면 위험이 나뉘지 않음, 2면 절반으로 줄어듦)."),
    list, detail,
    h("div", {class: "c5-guard"},
      h("p", null, h("b", null, "우연 거르기 1 · 날짜 섞기 "),
        `각 매매법의 날짜를 섞어 같은 탐색을 ${fmt.int(sh.runs || 0)}번: 섞은 자료의 최고 점수 중앙값 ${fmt.num(sh.null_median, 2)}, 위 10% ${fmt.num(sh.null_p90, 2)} · 진짜 최고 ${fmt.num(sh.real_best, 2)}. `,
        shWords),
      h("p", null, h("b", null, "우연 거르기 2 · 동전 봇 "),
        `동전 봇 ${fmt.int(cf.units_per_group || 36)}개짜리 묶음 ${fmt.int((cf.groups || []).length)}개로 같은 탐색: 최고 점수 `,
        (cf.groups || []).map((g) => fmt.num(g.score, 2)).join(" · "),
        ` · 진짜 최고 이상인 묶음 ${fmt.int(cf.beat_real || 0)}/${fmt.int((cf.groups || []).length)}`, " ", ui.pill("동전 봇", "ref"))),
    ui.refNote(vts, "5년 과거 시험의 비교도 같습니다."), capCaption());
}

/** The chosen combination's 5-year monthly curve (cumulative return on its own capital), its members (thin) and the
 *  coin-flip band of the same size (10-90% of random coin-flip groups, dashed median). */
function curveBox(d, t) {
  const months = d.months || [];
  const band = ((d.portfolio || {}).flip_band || {})[String(t.k)] || null;
  const members = t.units.map((u) => ({u, v: ((d.portfolio || {}).unit_curves || {})[u] || []}));
  const series = [
    ...(band ? [{values: band.p50, cls: "c5-l-flip", optional: true}] : []),
    ...members.map((m) => ({values: m.v, cls: "c5-l-mem"})),
    {values: t.curve || [], cls: "c5-l-combo", dot: true},
  ];
  const last = (a) => (a && a.length ? a[a.length - 1] : null);
  // a small total keeps one decimal (−0.4%, never a rounded "0%" for a loss)
  const pc = (x) => (x == null ? "—" : fmt.pct(x, Math.abs(x) < 0.1 ? 1 : 0));
  const chart = lineChart({series, band: band ? {lo: band.p10, hi: band.p90} : null,
    xlabels: [months[0], months[Math.floor(months.length / 2)], months[months.length - 1]], label: "조합의 5년 누적 수익률"});
  const flipOut = band && chart.dataset.omitted !== "0";
  const ddr = t.capital ? t.dd_usd / t.capital : null;
  return h("div", {class: "c5-curve"},
    h("p", {class: "c5-ctitle"}, h("b", null, t.units.map((u) => nm(d, u)).join(" + ")), ` · 5년 누적 (자기 자금 대비, 매달 다시 채운 합계)`),
    chart,
    h("div", {class: "c5-legend"},
      h("span", null, h("i", {class: "sw combo"}), `조합 ${pc(last(t.curve))}`),
      h("span", null, h("i", {class: "sw mem"}), `구성 매매법 ${fmt.int(members.length)}개 (각자 ${members.map((m) => pc(last(m.v))).join(" · ")})`),
      band ? h("span", null, flipOut ? null : h("i", {class: "sw flip"}),
        `동전 봇 ${fmt.int(t.k)}개 묶음: 가운데 ${fmt.pct(last(band.p50), 0)} (10~90% ${fmt.pct(last(band.p10), 0)} ~ ${fmt.pct(last(band.p90), 0)})`,
        flipOut ? " · 이 그림보다 훨씬 아래라 선은 생략" : " · 띠 = 10~90%", " · 참고") : null),
    h("p", {class: "an-note"}, `자금 ${dol(t.capital)} · 5년 손익 합계 ${dol(t.pnl, true)} · 가장 깊은 낙폭 ${dol(-t.dd_usd)} (`,
      ddr == null ? "—" : ddr < 1 ? `자금의 ${fmt.pct(ddr, 0, false)}` : `자금의 ${fmt.num(ddr, 1)}배`,
      ": 매달 다시 채워 넣은 돈까지 합친 낙폭). 누적이 −100%보다 낮으면 자금을 여러 번 다시 채웠다는 뜻입니다."));
}

/** A thin-line chart at the box's real width (like ui.curves), with an optional shaded band. */
function lineChart(o) {
  const box = h("div", {class: "c5-chart", role: "img", "aria-label": o.label || "곡선"});
  const fin = (a) => (a || []).filter((v) => v != null && Number.isFinite(v));
  // the scale follows the series that are always drawn (fit: true); a band / line far outside it is left out
  const base = o.series.filter((x) => !x.optional).flatMap((x) => fin(x.values));
  const vals = base.length >= 2 ? base : o.series.flatMap((x) => fin(x.values));
  if (vals.length < 2) { box.append(ui.notYet("자료 없음")); return box; }
  const span0 = Math.max(Math.max(0, ...vals) - Math.min(0, ...vals), 0.01);
  const inRange = (a) => fin(a).every((v) => v >= Math.min(0, ...vals) - span0 && v <= Math.max(0, ...vals) + span0);
  const band = o.band && inRange(o.band.lo) && inRange(o.band.hi) ? o.band : null;
  const series = o.series.filter((x) => !x.optional || inRange(x.values));
  box.dataset.omitted = String(o.series.length - series.length + (o.band && !band ? 1 : 0));
  const draw = (W) => {
    const H = 200, x0 = 52, x1 = W - 8, y0 = 8, y1 = H - 20;
    const all = [...series.flatMap((x) => fin(x.values)), ...(band ? [...fin(band.lo), ...fin(band.hi)] : [])];
    let lo = Math.min(0, ...all), hi = Math.max(0, ...all);
    const pad = (hi - lo) * 0.06 || 0.01;
    lo -= pad; hi += pad;
    const n = Math.max(...series.map((x) => (x.values || []).length));
    const X = (i) => x0 + (x1 - x0) * i / Math.max(1, n - 1), Y = (v) => y1 - (y1 - y0) * (v - lo) / (hi - lo);
    const dec = hi - lo < 0.2 ? 1 : 0;
    const kids = [];
    const ticks = [];
    for (const v of [0, lo + pad, hi - pad]) {       // zero first; a tick too close to one already placed is dropped
      if (ticks.some((t) => Math.abs(Y(t) - Y(v)) < 16)) continue;
      ticks.push(v);
      kids.push(s("line", {class: v === 0 ? "c5-zero" : "c5-grid", x1: x0, x2: x1, y1: Y(v).toFixed(1), y2: Y(v).toFixed(1)}));
      kids.push(s("text", {class: "c5-ax", x: x0 - 5, y: (Y(v) + 4).toFixed(1), "text-anchor": "end"}, v === 0 ? "0%" : fmt.pct(v, dec)));
    }
    if (band) {
      const up = band.hi.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`);
      const dn = band.lo.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).reverse();
      kids.push(s("path", {class: "c5-band", d: "M" + up.join(" L") + " L" + dn.join(" L") + " Z"}));
    }
    for (const sr of series) {
      const pts = (sr.values || []).map((v, i) => (v == null ? null : `${X(i).toFixed(1)},${Y(v).toFixed(1)}`)).filter(Boolean);
      if (pts.length > 1) kids.push(s("path", {class: sr.cls, d: "M" + pts.join(" L")}));
      if (sr.dot && pts.length) {
        const i = sr.values.length - 1;
        kids.push(s("circle", {class: "c5-dot", cx: X(i).toFixed(1), cy: Y(sr.values[i]).toFixed(1), r: 3}));
      }
    }
    const xl = o.xlabels || [];
    if (xl[0]) kids.push(s("text", {class: "c5-ax", x: x0, y: H - 4}, xl[0]));
    if (xl[1]) kids.push(s("text", {class: "c5-ax", x: ((x0 + x1) / 2).toFixed(0), y: H - 4, "text-anchor": "middle"}, xl[1]));
    if (xl[2]) kids.push(s("text", {class: "c5-ax", x: x1, y: H - 4, "text-anchor": "end"}, xl[2]));
    box.replaceChildren(s("svg", {class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H, "aria-hidden": "true"}, kids));
  };
  let lastW = 0;
  const fit = () => { const w = Math.round(box.clientWidth); if (w > 80 && w !== lastW) { lastW = w; draw(w); } };
  if (typeof ResizeObserver === "function") new ResizeObserver(fit).observe(box);
  requestAnimationFrame(() => { fit(); if (!lastW) draw(320); });
  return box;
}

// ---------------------------------------------------------------- walk-forward by calendar year
function walkCard({d, vts, v}) {
  const p = (d.portfolio || {})[v] || {};
  const wf = p.walk_forward || [], fl = p.walk_forward_flips || [];
  const nUnits = (p.units || []).length || 36;
  if (!wf.length) return null;
  const count = (rows) => ({med: rows.filter((r) => r.score_next > r.median_next).length, p75: rows.filter((r) => r.score_next > r.p75_next).length, n: rows.length,
    rmed: rows.filter((r) => r.return_next != null && r.ret_median_next != null && r.return_next > r.ret_median_next).length,
    rp75: rows.filter((r) => r.return_next != null && r.ret_p75_next != null && r.return_next > r.ret_p75_next).length});
  const a = count(wf), b = count(fl);
  const row = (r, flip) => h("div", {class: "c5-wf", role: "listitem"},
    h("div", {class: "c5-wf-h"}, h("b", null, `${r.pick_year}년에 고른 1위 → ${r.test_year}년`),
      h("span", {class: ["num", fmt.tone(r.mean_month_next, fmt.pct(r.mean_month_next, 1))]}, ` 그해 한 달 평균 ${fmt.pct(r.mean_month_next, 1)}`)),
    flip ? null : h("p", {class: "c5-wf-n"}, (r.units || []).map((u) => nm(d, u)).join(" + ")),
    h("div", {class: "c5-wf-bar", title: `전체 조합 중 ${fmt.pct(r.beat_share, 0, false)}보다 높음`},
      h("i", {style: {"--w": (Math.max(0, Math.min(1, r.beat_share || 0)) * 100).toFixed(1) + "%"}}),
      h("span", {class: "c5-mk m50"}), h("span", {class: "c5-mk m75"})),
    h("p", {class: "c5-wf-t"}, `점수: 고른 조합 ${fmt.num(r.score_next, 3)} · 그해 모든 조합(${fmt.int(r.n_combos)}개) 중앙값 ${fmt.num(r.median_next, 3)} · 상위 25% 선 ${fmt.num(r.p75_next, 3)} · 모든 조합 중 ${fmt.pct(r.beat_share, 0, false)}보다 높음`),
    r.mean_month_median_next != null ? h("p", {class: "c5-wf-t"}, `한 달 평균: 고른 조합 ${fmt.pct(r.mean_month_next, 1)} · 모든 조합 중앙값 ${fmt.pct(r.mean_month_median_next, 1)} · 상위 25% 선 ${fmt.pct(r.mean_month_p75_next, 1)} · 모든 조합 중 ${fmt.pct(r.ret_beat_share, 0, false)}보다 높음`) : null);
  return ui.card({plate: "다음 해에도 통했나", sub: "한 해에 고른 1위를 다음 해에 그대로 돌렸다면"},
    h("p", {class: "c5-sum"}, `매매법 ${fmt.int(nUnits)}개: ${fmt.int(a.n)}번 중 고른 조합이 다음 해 모든 조합의 가운데를 넘은 해는 점수로 ${fmt.int(a.med)}번(상위 25% ${fmt.int(a.p75)}번), 한 달 평균 수익으로 ${fmt.int(a.rmed)}번(상위 25% ${fmt.int(a.rp75)}번).`,
      fl.length ? ` 동전 봇 ${fmt.int(nUnits)}개로 같은 시험(참고): 점수로 ${fmt.int(b.med)}번, 수익으로 ${fmt.int(b.rmed)}번.` : "",
      (p.top || []).some((t) => t.trades != null && t.trades < 62) ? " 고른 조합에 거의 거래하지 않는 매매법이 들어 있으면 '덜 잃어서' 위에 섭니다." : ""),
    h("p", {class: "an-note"}, "막대 = 그해 2~5개 모든 조합 중 몇 %보다 점수가 높았나 · 가는 선 = 가운데(50%)와 상위 25%(75%) 자리. 고를 때는 그해 자료만 씁니다. 거의 모든 조합이 내리막만 탄 해에는 점수가 −1 근처에 몰리므로 한 달 평균 수익도 함께 봅니다."
      + (v === "active" ? " 단, '거래가 있는 것만' 목록 자체는 5년 전체의 거래 수를 보고 정했으므로 이 시험에는 미래 정보가 조금 섞여 있습니다." : "")),
    h("div", {class: "c5-wfs", role: "list"}, wf.map((r) => row(r, false))),
    fl.length ? ui.disclosure(`동전 봇 ${fmt.int(nUnits)}개로 같은 시험 (참고)`, h("div", {class: "c5-wfs", role: "list"}, fl.map((r) => row(r, true)))) : null,
    ui.refNote(vts));
}

// ---------------------------------------------------------------- correlation heatmap (36 x 36)
const MODES = [
  {id: "r", label: "하루 손익 상관", read: "같은 날 같이 벌고 같이 잃는 정도 (−1 ~ 1). 0.7 이상이면 사실상 같은 매매법처럼 움직입니다."},
  {id: "tail", label: "나쁜 날 겹침", read: "한쪽이 가장 나빴던 5%의 날(잃은 날만) 가운데 다른 쪽도 가장 나빴던 날의 비율 (두 방향 평균). 서로 상관없이 움직이면 약 5%, 나쁜 날이 똑같으면 100%. 나쁜 날 같이 무너지는지 봅니다."},
  {id: "coloss", label: "같이 잃은 날", read: "둘 중 하나라도 잃은 날 가운데 둘 다 잃은 날의 비율 (0 ~ 100%)."},
];
function triAt(n, i, j) {
  if (i === j) return null;
  const a = Math.min(i, j), b = Math.max(i, j);
  return a * n - (a * (a + 1)) / 2 + (b - a - 1);
}
function corrCard({d}) {
  const c = ((d.portfolio || {}).corr) || {};
  const units = d.strategies || [];
  const n = units.length;
  if (!n || !(c.r || []).length) return null;
  let mode = local.get("c5-corr", "r");
  if (!MODES.some((m) => m.id === mode)) mode = "r";
  const read = h("p", {class: "an-note"});
  const slot = h("div", {class: "c5-heatwrap"});
  const info = h("p", {class: "c5-heatinfo", "aria-live": "polite"}, "칸을 누르면 두 매매법과 숫자가 나옵니다.");
  const SHARE = {tail: true, coloss: true};                    // 0..1 modes: coloured by their order
  const val = (m, i, j) => (i === j ? (m === "r" ? 1 : null) : (c[m] || [])[triAt(n, i, j)]);
  function cellWords(i, j) {
    const pct = (x) => (x == null ? "—" : fmt.pct(x, 0, false));
    return `${nm(d, units[i])} × ${nm(d, units[j])}: 하루 손익 상관 ${fmt.num(val("r", i, j), 2)} · 나쁜 날 겹침 ${pct(val("tail", i, j))} · 같이 잃은 날 ${pct(val("coloss", i, j))}`;
  }
  function draw() {
    // 나쁜 날 겹침 / 같이 잃은 날 (0..1) bunch up for most pairs: their colour follows each pair's ORDER among the pairs
    // above 0 (the lowest the palest, the highest the strongest), so the bunch spreads out; 0 (a strategy that never
    // trades) stays palest
    const cv = SHARE[mode] ? (c[mode] || []).filter((x) => x != null && x > 0).sort((x, y) => x - y) : [];
    const order = (v) => {                                     // share of the pairs at or below v (0..1)
      let lo = 0, hi = cv.length;
      while (lo < hi) { const m = (lo + hi) >> 1; if (cv[m] <= v) lo = m + 1; else hi = m; }
      return cv.length > 1 ? (lo - 1) / (cv.length - 1) : 0.5;
    };
    read.textContent = (MODES.find((m) => m.id === mode) || MODES[0]).read
      + (cv.length ? ` 색은 순서대로: 가장 낮은 쌍(${fmt.pct(cv[0], 0, false)})이 가장 연하고 가장 높은 쌍(${fmt.pct(cv[cv.length - 1], 0, false)})이 가장 진합니다. 가운데 쌍은 ${fmt.pct(cv[Math.floor(cv.length / 2)], 0, false)}.` : "");
    const cell = 12, lab = 0, W = lab + n * cell, H = n * cell;
    const kids = [];
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        const v = val(mode, i, j);
        const cls = v == null ? "none" : v >= 0 ? "pos" : "neg";
        const a = v == null ? 0 : SHARE[mode] ? (v > 0 ? Math.max(0, Math.min(1, order(v))) : 0) : Math.min(1, Math.abs(v));
        kids.push(s("rect", {class: ["c5-hc", cls, i === j ? "diag" : ""], x: lab + j * cell, y: i * cell, width: cell - 1, height: cell - 1,
          style: {"--a": a.toFixed(3)}, dataset: {i, j}}));
      }
    }
    const svg = s("svg", {class: "c5-heat", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "5년 상관 지도 36 × 36"}, kids);
    svg.addEventListener("click", (e) => {
      const t = e.target;
      if (!t || !t.dataset || t.dataset.i == null) return;
      svg.querySelectorAll(".sel").forEach((x) => x.classList.remove("sel"));
      t.classList.add("sel");
      const i = Number(t.dataset.i), j = Number(t.dataset.j);
      info.textContent = i === j ? nm(d, units[i]) : cellWords(i, j);
    });
    const names = h("ol", {class: "c5-heatnames"}, units.map((u) => h("li", null, nm(d, u))));
    put(slot, h("div", {class: "c5-heatgrid"}, svg, names));
  }
  const seg = ui.seg(MODES.map((m) => ({id: m.id, label: m.label})), mode, (id) => { mode = id; local.set("c5-corr", id); draw(); }, {label: "상관 보기", scroll: true});
  draw();
  // the most and least related pairs (words, so a phone does not need to hit a 9 px cell)
  const pairs = [];
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) { const v = val("r", i, j); if (v != null) pairs.push([v, i, j]); }
  pairs.sort((x, y) => y[0] - x[0]);
  const pl = (arr) => arr.map(([v, i, j]) => h("li", null, `${nm(d, units[i])} × ${nm(d, units[j])} `, h("b", {class: "num"}, fmt.num(v, 2)))).slice(0, 5);
  const cl = c.clusters || [];
  return ui.card({plate: "5년 상관 지도", sub: "기존 36 · 매달 새로 시작한 계좌의 하루 손익"},
    seg, read, slot, info,
    h("div", {class: "c5-cols"},
      h("div", null, h("p", {class: "c5-sub"}, "가장 같이 움직인 쌍"), h("ul", {class: "c5-pairs"}, pl(pairs.slice(0, 5)))),
      h("div", null, h("p", {class: "c5-sub"}, "가장 따로 움직인 쌍"), h("ul", {class: "c5-pairs"}, pl(pairs.slice(-5).reverse())))),
    h("p", {class: "an-note"}, cl.length ? `상관 0.7 이상으로 묶이는 무리 ${fmt.int(cl.length)}개: ` + cl.slice(0, 4).map((g) => g.map((u) => nm(d, u)).join(" · ")).join(" / ")
      : "상관 0.7 이상으로 묶이는 무리는 없습니다."),
    h("p", {class: "an-note"}, "색이 진할수록 숫자가 큽니다 (강조색 = +, 회색빛 = −, 대각선 = 자기 자신). 오른쪽(휴대폰은 아래) 번호 목록이 칸의 줄·칸 순서입니다."));
}

// ---------------------------------------------------------------- merged signal rules
const FAM_KO = {AND: "둘 다 (AND)", FILTER: "거르기 (FILTER)", VOTE: "다수결 (VOTE)", MTF: "위 봉 확인 (MTF)"};
function ruleWords(d, r) {
  const p = r.parts || [];
  if (r.family === "AND") return `${nm(d, p[0])} 그리고 ${nm(d, p[1])} · 같은 코인·같은 방향 ${p[2] === "0" ? "같은 봉" : `${p[2]}봉 안`} · ${TF_KO[p[3]] || p[3]}`;
  if (r.family === "FILTER") return `${nm(d, p[0])}, 단 ${nm(d, p[1])}의 최근 신호(${p[2]}봉 안)가 같은 방향일 때만 · ${TF_KO[p[3]] || p[3]}`;
  if (r.family === "VOTE") return `36개 중 ${p[0]}개 이상이 같은 봉에서 같은 방향 · ${TF_KO[p[1]] || p[1]}`;
  if (r.family === "MTF") return `${nm(d, p[0])} ${TF_KO[p[1]] || p[1]}, 단 닫힌 ${TF_KO[p[2]] || p[2]}봉 신호가 같은 방향일 때만 (${p[3] === "recent" ? "최근 3봉 안" : "기간 무관"})`;
  return r.key;
}
function mergedCard({d}) {
  const m = d.merged || {};
  if (!m.trials) return null;
  const fam = m.families || {};
  const winLabels = m.windows || ["2021-22", "2023-24", "2025-26"];
  const famRows = Object.keys(FAM_KO).filter((k) => fam[k]).map((k) => [k, fam[k]]);
  const pg = ui.pager({size: 5, empty: "규칙이 없습니다", row: (r, i) => h("div", {class: "lrow c5-mrow", role: "listitem"},
    h("span", {class: "rk"}, `${fmt.int(i + 1)}`),
    h("span", {class: "lname c5-wrap"}, ruleWords(d, r)),
    h("span", {class: ["ret num", fmt.tone(r.mean, fmt.pct(r.mean, 2))]}, fmt.pct(r.mean, 2)),
    h("span", {class: "meta"},
      h("span", null, `거래 ${fmt.int(r.n)}건 · 이긴 거래 ${fmt.pct(r.win, 0, false)}`),
      (r.alone || []).filter(Boolean).length ? h("span", null, "혼자일 때 ", (r.alone || []).map((a) => (a ? fmt.pct(a.mean, 2) : "—")).join(" / ")) : null,
      h("span", {class: "c5-wins"}, (r.w || []).map((w, j) => h("i", {class: ["c5-win", w[1] == null ? "" : fmt.tone(w[1])], title: `${winLabels[j]} 거래 ${fmt.int(w[0])}건`},
        `${winLabels[j]} ${w[1] == null ? "—" : fmt.pct(w[1], 2)}`))),
      r.bh ? (r.shuffle_pass ? ui.pill("두 단계 다 넘음", "accent") : ui.pill("거르기 1만 넘음", "thin")) : ui.pill("보정 못 넘음", "warn", "여러 번 시험한 것을 보정하면 우연과 구별되지 않음"),
      r.consistent ? ui.pill("세 구간 모두 +", "thin") : null,
      r.null_rank_p != null ? h("span", null, r.shuffle_pass ? "섞은 비교보다 높음 (그래도 보정 전)" : "섞은 비교와 비슷") : null))});
  pg.set((m.survivors && m.survivors.length ? m.survivors : m.top) || []);
  const sg = m.singles || {};
  return ui.card({plate: "신호 합치기", sub: "두 매매법 신호를 묶은 새 규칙"},
    h("div", {class: "stats s4 c5-stats"},
      ui.stat("시험한 규칙", fmt.int(m.trials), "모두 셈"),
      ui.stat("판단할 만큼 거래", fmt.int(m.tested), `거래 ${fmt.int(m.min_trades)}건 이상`),
      ui.stat("우연 거르기 1", fmt.int(m.bh_pass), `여러 번 시험 보정 (${fmt.pct(m.fdr, 0, false)})`),
      ui.stat("둘 다 넘음", fmt.int(m.both_pass), "+ 시간 섞은 비교")),
    h("p", {class: "c5-sum"}, m.both_pass ? `${fmt.int(m.trials)}개를 시험해 두 단계를 모두 넘은 규칙 ${fmt.int(m.both_pass)}개 (아래).`
      : `${fmt.int(m.trials)}개를 시험해 두 단계를 모두 넘은 규칙은 없습니다. 아래는 그중 숫자가 가장 나았던 ${fmt.int((m.top || []).length)}개입니다 (넘지 못함). ${fmt.int(m.tested)}개 가운데 가장 좋아 보이는 것만 골랐으므로 이 숫자들은 운이 섞여 부풀려져 있습니다.`),
    h("p", {class: "an-note"}, "오른쪽 = 거래 한 건이 계좌에 남긴 평균 손익 (보통 배수 30배·30%, 수수료·펀딩 뒤) · 세 구간 = 2021-22 / 2023-24 / 2025-26 평균 · 섞은 비교 = 짝 신호를 시간만 밀어서 39번 다시 계산"),
    pg.el,
    ui.table([{label: "종류", l: true, get: ([k]) => FAM_KO[k]}, {label: "시험", get: ([, f]) => fmt.int(f.trials)}, {label: "판단", get: ([, f]) => fmt.int(f.tested)},
      {label: "거르기 1", get: ([, f]) => fmt.int(f.bh)}, {label: "둘 다", get: ([, f]) => fmt.int(f.both)}], famRows),
    h("p", {class: "an-note"}, `참고: 합치지 않은 매매법·봉 ${fmt.int(sg.cells || 0)}칸 중 거래당 평균이 + 인 칸 ${fmt.int(sg.positive_mean || 0)}개, 같은 기준(우연 거르기 1)을 넘은 칸 ${fmt.int(sg.bh_pass || 0)}개.`),
    ui.disclosure("규칙 만드는 법 (미래 정보 없음)", h("ul", {class: "c5-how"},
      h("li", null, "AND: 두 매매법이 같은 코인·같은 방향 신호를 k봉 안에 냄 (k = 0, 1, 3). 나중 신호가 나온 봉에서 들어감."),
      h("li", null, "FILTER: A 신호가 날 때 B의 가장 최근 신호(N봉 안, 같은 봉 포함)가 같은 방향이면 들어감 (N = 4, 16)."),
      h("li", null, "VOTE: 같은 봉에서 36개 중 K개 이상이 같은 방향 (K = 2, 3, 4, 5, 6, 8). 양쪽이 다 K를 넘으면 안 들어감."),
      h("li", null, "MTF: 같은 매매법의 아래 봉 신호를, 이미 닫힌 위 봉의 가장 최근 신호가 같은 방향일 때만."),
      h("li", null, "신호는 봉이 닫힐 때 알고, 다음 봉 시가에 들어갑니다. 결과는 신호 하나 = 거래 하나 (계좌·포지션 제한 없음)."))),
    capCaption());
}

// ---------------------------------------------------------------- one shared account
function sharedCard({d, v}) {
  const sh = (d.shared || {})[v] || [];
  if (!sh.length) return null;
  const pg = ui.pager({size: 1, row: (x) => {
    const a = x.separate || {}, b = x.shared || {};
    const cmpRow = (label, va, vb) => h("div", {class: "c5-srow"}, h("span", {class: "k"}, label), h("b", {class: "num"}, va), h("b", {class: "num"}, vb));
    return h("div", {class: "c5-shared", role: "listitem"},
      h("p", {class: "c5-ctitle"}, h("b", null, x.units.map((u) => nm(d, u)).join(" + ")), ` · 계좌 ${fmt.int(x.accounts)}개 · 자금 ${dol(x.capital)}`),
      h("div", {class: "c5-sgrid"},
        h("div", {class: "c5-srow head"}, h("span", null, ""), h("span", null, "따로 (지금처럼)"), h("span", null, "한 계좌로")),
        cmpRow("한 달 평균", fmt.pct(a.mean_month, 1), fmt.pct(b.mean_month, 1)),
        cmpRow("이긴 달", fmt.pct(a.win_months, 0, false), fmt.pct(b.win_months, 0, false)),
        cmpRow("가장 깊은 낙폭", dol(-a.dd_usd), dol(-b.dd_usd)),
        cmpRow("5년 손익 합계", dol(a.pnl, true), dol(b.pnl, true)),
        cmpRow("거래 수", fmt.int(a.trades), fmt.int(b.trades))),
      lineChart({series: [{values: a.curve || [], cls: "c5-l-sep"}, {values: b.curve || [], cls: "c5-l-combo", dot: true}],
        xlabels: [(d.months || [])[0], null, (d.months || [])[(d.months || []).length - 1]], label: "따로 vs 한 계좌"}),
      h("div", {class: "c5-legend"}, h("span", null, h("i", {class: "sw sep"}), "따로 (굵은 회색)"), h("span", null, h("i", {class: "sw combo"}), "한 계좌"),
        h("span", null, "5년 누적, 자금 대비")),
      h("p", {class: "an-note"}, `한 계좌에 들어온 신호 ${fmt.int(b.signals)}개 중: 같은 코인을 이미 같은 방향으로 들고 있어 건너뜀 ${fmt.int(b.same_side_skipped)}개 · `,
        h("b", null, `반대 방향 충돌 ${fmt.int(b.conflicts)}개`), ` · 크기 규칙에 막힘 ${fmt.int(b.refused)}개 · 파산한 달 ${fmt.int(b.bust_months)}개`));
  }});
  pg.set(sh);
  return ui.card({plate: "한 계좌로 합치면", sub: "점수 상위 5개 조합 · 다음 / 이전으로 넘김"},
    h("p", {class: "an-note"}, "같은 돈을 계좌 하나에 넣고 구성 매매법의 모든 봉 신호를 받으면: 코인마다 포지션 하나, 그 코인을 들고 있으면 새 신호는 건너뜀 (반대 방향이면 충돌로 셈). 한 번에 거는 크기는 계좌 하나 몫 (잔고 ÷ 계좌 수)."),
    pg.el, capCaption());
}

// ---------------------------------------------------------------- methods + caveat
function methodsCard({d}) {
  const mt = d.methods || {}, pr = d.parity || {}, v4 = pr.v4_same_windows || {};
  const bs = mt.best_share || {};
  const tm = mt.timings || {};
  const parWords = pr.cells ? `${fmt.int(pr.same_final)}/${fmt.int(pr.cells)}칸 최종 잔고 같음 · 거래 수 같음 ${fmt.int(pr.same_trades)}/${fmt.int(pr.cells)} · 프로필 카드 ${fmt.int(pr.cards_same)}/${fmt.int(pr.cards_cells)}`
    + (pr.cards_blank ? ` (${fmt.int(pr.cards_blank)}칸은 신호가 없어 카드에 숫자 없음)` : "") : "—";
  return ui.card({plate: "어떻게 계산했나", sub: "방법 · 연구 숫자와 맞춰 보기 · 주의"},
    h("div", {class: "c5-caveat"}, h("b", null, "주의 "), mt.caveat || ""),
    ui.kv([
      ["기간", `${(d.months || [])[0] || ""} ~ ${(d.months || [])[(d.months || []).length - 1] || ""} (한국 시간 달, ${fmt.int((d.months || []).length)}달)`],
      ["계좌", mt.accounts],
      ["크기·레버리지", mt.sizing],
      ["비용", (mt.costs || {}).words],
      ["합친 규칙", mt.merged_sizing],
      ["연구 숫자와 맞춰 보기", [pr.agree ? ui.pill("일치", "accent") : ui.pill("차이 있음", "warn"), " ", parWords]],
      ["v4 규칙이면", v4.why ? `${v4.why} → 같은 창의 잔고 배수 중앙값 연구 ${fmt.num(v4.median_multiple_research, 3)} · v4 ${fmt.num(v4.median_multiple_v4, 3)}, 파산 연구 ${fmt.int(v4.bust_research)} · v4 ${fmt.int(v4.bust_v4)}` : null],
      ["'best' 신호 비율", Object.entries(bs).map(([tf, x]) => `${TF_KO[tf] || tf} ${fmt.pct(x.share, 1, false)} (설정 ${fmt.pct(x.p_best_config, 1, false)})`).join(" · ")],
    ]),
    ui.disclosure("시험 횟수와 다시 만드는 법", h("div", {class: "stack tight"},
      h("p", {class: "an-note"}, `합친 규칙 ${fmt.int((mt.trials || {}).merged)}개 · 날짜 섞은 탐색 ${fmt.int((mt.trials || {}).portfolio_shuffles)}번 · 동전 봇 ${fmt.int((mt.trials || {}).coin_flip_units)}개(${fmt.int((mt.trials || {}).coin_flip_groups)}묶음) · ${(mt.trials || {}).portfolio_combos_searched || ""}`),
      h("p", {class: "an-note"}, `계산 시간 ${fmt.num((tm.total_s || 0) / 60, 1)}분 · 코드 ${mt.git_head || "—"} · ${mt.generator || ""}`),
      h("p", {class: "an-note"}, "설명: docs/combo5y.md"))),
    h("p", {class: "an-note"}, d.label || "설명용, 판정 아님"));
}


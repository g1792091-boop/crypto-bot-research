// 분석 › 손실 크기 규칙 (size5y, the 36 only): the same 5-year entries and exits of the 36 with only the position size
// changed (지금 v4 / 손절 = 잔고 0.5·1·2% / 배수 절반). Pre-registered in docs/size5y.md; descriptive (설명용, 판정 아님);
// the live rules do not change before the verdict.
//   GET /api/v4/size5y                      the study as committed (paperbot/dash/data/size5y.json, dash/more/size5y.py)
//   GET /api/v4/size5y/cell?s=&tf=          one strategy x timeframe with its monthly curves (the drill-down)
// Cards: the head, the caveat, the plain reading (sentences built only from the file's numbers), the comparison table
// (rules as columns; timeframe and period switches), the pooled monthly equity curves (log scale), the per-strategy
// list (tap: its own table and curves). Coin flips are 참고 (refNote); money has its caption.
import {h, s, ui, fmt, put, motion} from "../core/pb.js";
import {viewHead, dimSeg} from "./analysis-kit.js";

const RULE_CLS = {v4: "v4", r05: "r05", r1: "r1", r2: "r2", half: "half"};
const ASSUME_5Y = "5년 과거 시험 · 같은 진입·같은 청산 · 크기만 다름 · 배수 = 끝 잔고 ÷ 시작 잔고";
const TF_OPTS = [{id: "all", label: "네 봉 전체"}, {id: "15m", label: "15분"}, {id: "30m", label: "30분"}, {id: "1h", label: "1시간"}, {id: "4h", label: "4시간"}];
const pc0 = (x) => (x == null ? "—" : fmt.pct(x, 0, false));
const pc1 = (x, sign = false) => (x == null ? "—" : fmt.pct(x, 1, sign));
const mx = (x) => (x == null ? "—" : `${fmt.num(x, x < 0.1 ? 3 : 2)}배`);

/** The compact metric row [mult, cagr, mdd, worst, pos, calmar, bust, taken, skipped, bust_at] as an object. */
export function mrow(a, keys) {
  const k = keys || ["mult", "cagr", "mdd", "worst_month", "pos_months", "calmar", "bust", "taken", "skipped", "bust_at"];
  const o = {};
  k.forEach((name, i) => { o[name] = a ? a[i] ?? null : null; });
  return o;
}

/** Plain sentences from the pooled numbers of one timeframe key (never typed-in results). */
export function reading(doc, key = "all") {
  const P = ((doc.pooled || {})[key]) || {}, F = ((doc.flips || {})[key]) || {};
  const K = doc.m_keys;
  const g = (r, pk = "full") => mrow(((P[r] || {})[pk] || {}).m, K);
  const v4 = g("v4"), r1 = g("r1"), r05 = g("r05"), half = g("half");
  const n = ((P.v4 || {}).full || {}).n || 0;
  if (!n) return [];
  const out = [];
  const lv4 = (P.v4 || {}).loss_med, l1 = (P.r1 || {}).loss_med, lh = (P.half || {}).loss_med;
  out.push(`지금 v4 규칙에서는 지는 거래 한 번에 잔고의 ${pc1(lv4)}(가운데 값)를 잃었고, 가장 크게는 ${pc1((P.v4 || {}).loss_max)}를 잃었습니다. 1% 규칙에서는 ${pc1(l1)}였습니다.`);
  const ret = r1.mult != null && v4.mult != null
    ? (r1.mult > v4.mult ? `수익 쪽도 덜 잃었습니다 (5년 뒤 잔고가 시작의 ${mx(v4.mult)} → ${mx(r1.mult)})` : `대신 5년 뒤 잔고는 시작의 ${mx(v4.mult)} → ${mx(r1.mult)}로 더 적었습니다`)
    : "";
  out.push(`1% 규칙이면 ${n}칸을 모은 5년 최대 낙폭이 ${pc0(v4.mdd)}에서 ${pc0(r1.mdd)}로, 가장 나쁜 달이 ${pc1(v4.worst_month)}에서 ${pc1(r1.worst_month)}로 바뀌고, ${ret}.`);
  const b = (r) => ((P[r] || {}).full || {}).busts ?? 0, up = (r) => ((P[r] || {}).full || {}).up ?? 0;
  out.push(`5년 한 계좌가 파산한 칸: v4 ${fmt.int(b("v4"))}칸 → 1% 규칙 ${fmt.int(b("r1"))}칸 → 0.5% 규칙 ${fmt.int(b("r05"))}칸 (${fmt.int(n)}칸 중).`);
  if (r05.mult != null && r05.mult < 1) {
    out.push(`그래도 0.5% 규칙에서도 5년 뒤 $5,000보다 늘어난 칸은 ${fmt.int(up("r05"))}칸뿐입니다 (v4 ${fmt.int(up("v4"))}칸). 거래당 평균이 마이너스면 크기를 줄여도 잃는 속도만 느려집니다.`);
  }
  if (lh != null && lv4 != null && Math.abs(lh - lv4) < 0.25 * lv4) {
    out.push(`배수 절반은 거의 같았습니다 (손실 한 번 ${pc1(lv4)} → ${pc1(lh)}, 5년 배수 ${mx(v4.mult)} → ${mx(half.mult)}). 증거금 비율을 그대로 두면 거래소 한도와 '손절 손실 ≤ 잔고 15%' 확인 때문에 들어가는 크기가 거의 줄지 않기 때문입니다.`);
  }
  const f4 = mrow(((F.v4 || {}).full || {}).m, K), f1 = mrow(((F.r1 || {}).full || {}).m, K);
  if (f4.mult != null && f1.mult != null) {
    out.push(`참고: 동전 봇도 같은 규칙을 달면 ${mx(f4.mult)} → ${mx(f1.mult)}였습니다. 크기 규칙은 매매법이 아니라 '얼마나 걸었나'만 바꿉니다.`);
  }
  return out;
}

// ---------------------------------------------------------------- the comparison table (rules as columns)
const ROWS = [
  {k: "mult", label: "5년 뒤 잔고 (시작의 몇 배)", f: (m) => mx(m.mult), tone: (m) => (m.mult == null ? null : m.mult - 1)},
  {k: "cagr", label: "1년 평균 (복리)", f: (m) => pc1(m.cagr, true), tone: (m) => m.cagr},
  {k: "mdd", label: "최대 낙폭", f: (m) => pc0(m.mdd)},
  {k: "worst_month", label: "가장 나쁜 달", f: (m) => pc1(m.worst_month, true), tone: (m) => m.worst_month},
  {k: "pos_months", label: "플러스인 달", f: (m) => pc0(m.pos_months)},
  {k: "calmar", label: "1년 평균 ÷ 최대 낙폭", f: (m) => (m.calmar == null ? "—" : fmt.num(m.calmar, 2, true)), tone: (m) => m.calmar},
];

function compareCard(doc, env) {
  const box = h("div", {class: "sz-cmp"});
  const tf = dimSeg("sz-tf", TF_OPTS, "all", () => draw(), true);
  const per = dimSeg("sz-per", (doc.periods || []).map((p) => ({id: p.key, label: p.key === "full" ? "5년" : p.ko})), "full", () => draw(), true);
  const rules = doc.rules || [];
  function draw() {
    const key = tf.get(), pk = per.get();
    const P = (doc.pooled || {})[key] || {}, F = (doc.flips || {})[key] || {};
    const col = (r) => mrow(((P[r.key] || {})[pk] || {}).m, doc.m_keys);
    const fcol = (r) => mrow(((F[r.key] || {})[pk] || {}).m, doc.m_keys);
    const cell = (txt, t) => h("span", {class: ["num", t == null ? "" : fmt.tone(t)]}, txt);
    const rowsA = ROWS.map((row) => ({label: row.label, get: (r) => cell(row.f(col(r)), row.tone ? row.tone(col(r)) : null)}));
    const pp = (r) => (P[r.key] || {})[pk] || {};
    const rowsB = [
      {label: "파산한 칸 (잔고 $10 미만)", get: (r) => cell(`${fmt.int(pp(r).busts ?? 0)} / ${fmt.int(pp(r).n ?? 0)}`)},
      {label: "$5,000보다 늘어난 칸", get: (r) => cell(`${fmt.int(pp(r).up ?? 0)} / ${fmt.int(pp(r).n ?? 0)}`)},
      {label: "칸마다 배수의 가운데 값", get: (r) => cell(mx(pp(r).med_mult))},
      {label: "칸마다 최대 낙폭의 가운데 값", get: (r) => cell(pc0(pp(r).med_mdd))},
    ];
    const rowsC = pk === "full" ? [
      {label: "지는 거래 한 번 (가운데 / 최대)", get: (r) => cell(`${pc1((P[r.key] || {}).loss_med)} / ${pc1((P[r.key] || {}).loss_max)}`)},
      {label: "30일 계좌: 파산한 창", get: (r) => cell(`${fmt.int(((P[r.key] || {}).w30 || [])[1] ?? 0)} / ${fmt.int(((P[r.key] || {}).w30 || [])[0] ?? 0)}`)},
      {label: "30일 계좌: 플러스로 끝난 비율", get: (r) => cell(pc0(((P[r.key] || {}).w30 || [])[2]))},
      {label: "30일 계좌: 가운데 수익 / 가장 나쁜", get: (r) => { const w = (P[r.key] || {}).w30 || []; return cell(`${pc1(w[3], true)} / ${pc1(w[4], true)}`, w[3]); }},
    ] : [];
    const rowsF = [{label: "동전 봇 같은 규칙 (참고)", get: (r) => cell(mx(fcol(r).mult), fcol(r).mult == null ? null : fcol(r).mult - 1)}];
    const all = [...rowsA, ...rowsB, ...rowsC, ...rowsF];
    const cols = [{label: "", l: true, get: (x) => h("span", {class: "sz-rl"}, x.label)},
      ...rules.map((r) => ({label: h("span", {class: ["sz-key", RULE_CLS[r.key]]}, r.short), get: (x) => x.get(r)}))];
    put(box, ui.table(cols, all),
      h("p", {class: "an-note"}, key === "all" ? "모은 것 = 144칸(기존 36 × 네 봉)의 5년 계좌(각 $5,000)를 그냥 더한 잔고, 달마다 찍은 점으로 낙폭을 잽니다." : `모은 것 = 이 봉의 36칸 5년 계좌를 그냥 더한 잔고 (달 단위 낙폭).`,
        pk !== "full" ? " 구간마다 $5,000에서 새로 시작한 계좌입니다." : " 30일 계좌 = 지금 모의 계좌처럼 30일마다 새 $5,000."),
      ui.assume("closed", ASSUME_5Y), ui.refNote(env.verdictTs, "동전 봇 줄은 같은 크기 규칙을 무작위 진입에 단 것입니다."));
  }
  draw();
  return ui.card({plate: "규칙 비교", sub: "같은 거래 · 크기만 다름"}, h("div", {class: "sz-filters"}, tf.el, per.el), box);
}

// ---------------------------------------------------------------- curves (log scale, monthly)
/** {series: [{key, values}], months: ['YYYY-MM'], height} -> a log-scale line chart drawn at the box's real width. */
export function logCurves(o) {
  const box = h("div", {class: "sz-curves", style: {height: (o.height || 220) + "px"}});
  const vals = o.series.flatMap((sr) => sr.values.filter((v) => v != null && v > 0));
  if (vals.length < 2) { box.style.height = ""; box.append(ui.notYet("곡선 없음")); return box; }
  const draw = (W) => {
    const H = o.height || 220, x0 = 46, x1 = W - 8, y0 = 8, y1 = H - 22;
    const lo = Math.log10(Math.max(Math.min(...vals, 1), 1e-4)), hi = Math.log10(Math.max(...vals, 1));
    const span = hi - lo || 1;
    const n = Math.max(...o.series.map((sr) => sr.values.length));
    const X = (i) => x0 + (x1 - x0) * i / Math.max(1, n - 1);
    const Y = (v) => y1 - (y1 - y0) * (Math.log10(Math.max(v, 1e-4)) - lo) / span;
    const kids = [];
    // 1 (the start) first, then whole decades, then the two ends; a label closer than 16 px to a kept one is left out
    const cand = [1];
    for (let e = Math.ceil(lo); e <= Math.floor(hi); e++) cand.push(10 ** e);
    cand.push(10 ** lo, 10 ** hi);
    const ticks = [];
    for (const t of cand) if (ticks.every((k) => Math.abs(Y(k) - Y(t)) >= 16)) ticks.push(t);
    for (const t of ticks) {
      const y = Y(t).toFixed(1);
      kids.push(s("line", {class: t === 1 ? "base" : "grid", x1: x0, x2: x1, y1: y, y2: y}));
      kids.push(s("text", {class: "ax", x: x0 - 5, y: (Number(y) + 4).toFixed(1), "text-anchor": "end"}, t >= 1 ? `${fmt.num(t, 0)}배` : `${fmt.num(t, t < 0.01 ? 3 : 2)}배`));
    }
    for (const sr of o.series) {
      const pts = sr.values.map((v, i) => (v == null ? null : `${X(i).toFixed(1)},${Y(v).toFixed(1)}`)).filter(Boolean);
      if (pts.length > 1) kids.push(s("path", {class: ["sz-line", RULE_CLS[sr.key] || ""], d: "M" + pts.join(" L")}));
    }
    const m = o.months || [];
    const yrs = m.map((x, i) => [x, i]).filter(([x]) => x.endsWith("-01"));
    const step = W < 520 ? 2 : 1;
    yrs.filter((_y, j) => j % step === 0).forEach(([x, i]) => kids.push(s("text", {class: "ax", x: X(i + 1).toFixed(1), y: H - 4, "text-anchor": "middle"}, x.slice(0, 4))));
    box.replaceChildren(s("svg", {class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": o.label || "규칙별 잔고 곡선"}, kids));
  };
  let lastW = 0;
  const fit = () => { const w = Math.round(box.clientWidth); if (w > 60 && w !== lastW) { lastW = w; draw(w); } };
  if (typeof ResizeObserver === "function") new ResizeObserver(fit).observe(box);
  requestAnimationFrame(() => { fit(); if (!lastW) draw(320); });
  return box;
}

const legend = (rules) => h("div", {class: "sz-legend", role: "list"}, rules.map((r) => h("span", {class: "sz-leg", role: "listitem"},
  h("i", {class: ["sz-sw", RULE_CLS[r.key]]}), r.ko)));

function curvesCard(doc) {
  const box = h("div");
  const tf = dimSeg("sz-ctf", TF_OPTS, "all", () => draw(), true);
  function draw() {
    const P = (doc.pooled || {})[tf.get()] || {};
    // the curve starts at 1 (the start) and then has one point per month end
    const series = (doc.rules || []).map((r) => ({key: r.key, values: [1, ...(((P[r.key] || {}).full || {}).curve || [])]}));
    put(box, logCurves({series, months: ["시작", ...(doc.months || [])], label: "모은 36의 달별 잔고, 규칙마다"}));
  }
  draw();
  return ui.card({plate: "모은 36 · 달별 잔고", sub: "세로는 로그 눈금 (1배 = 시작)"},
    h("div", {class: "sz-filters"}, tf.el), box, legend(doc.rules || []),
    h("p", {class: "an-note"}, "칸마다 $5,000 계좌 하나를 5년 동안 그대로 굴려서 더한 잔고 ÷ 시작 잔고. 파산한 칸은 그 뒤로 거의 0으로 남습니다."),
    ui.assume("closed", ASSUME_5Y));
}

// ---------------------------------------------------------------- per strategy x timeframe
function cellDetail(c, doc, env, cache) {
  const body = h("div", {class: "sz-detail"}, motion.shimmer(2));
  const key = c.s + "@" + c.tf;
  (async () => {
    let d = cache.get(key);
    if (!d) {
      try { d = await env.ctx.api(`/api/v4/size5y/cell?s=${encodeURIComponent(c.s)}&tf=${encodeURIComponent(c.tf)}`); } catch (e) {
        if (env.ctx.alive() && body.isConnected) put(body, ui.errorBox(e));
        return;
      }
      cache.set(key, d);
    }
    if (!env.ctx.alive()) return;                   // a detached body (row closed meanwhile) is harmless to fill
    const rules = doc.rules || [];
    const per = (doc.periods || []);
    const row = (r, pk) => mrow(((d.r || {})[r.key] || {})[pk], doc.m_keys);
    const cols = [{label: "", l: true, get: (x) => h("span", {class: "sz-rl"}, x.label)},
      ...rules.map((r) => ({label: h("span", {class: ["sz-key", RULE_CLS[r.key]]}, r.short), get: (x) => x.get(r)}))];
    const num = (t, tone) => h("span", {class: ["num", tone == null ? "" : fmt.tone(tone)]}, t);
    const lines = [
      {label: "5년 뒤 잔고", get: (r) => { const m = row(r, "full"); return num(mx(m.mult), m.mult == null ? null : m.mult - 1); }},
      {label: "최대 낙폭", get: (r) => num(pc0(row(r, "full").mdd))},
      {label: "가장 나쁜 달", get: (r) => num(pc1(row(r, "full").worst_month, true), row(r, "full").worst_month)},
      {label: "파산", get: (r) => { const m = row(r, "full"); return num(m.bust ? (m.bust_at ? `${fmt.dayKey(m.bust_at).slice(0, 7)} 파산` : "파산") : "없음", m.bust ? -1 : null); }},
      ...per.filter((p) => p.key !== "full").map((p) => ({label: `${p.ko} 배수`, get: (r) => { const m = row(r, p.key); return num(mx(m.mult) + (m.bust ? " 파산" : ""), m.mult == null ? null : m.mult - 1); }})),
      {label: "지는 거래 한 번 (가운데)", get: (r) => num(pc1((((d.r || {})[r.key] || {}).loss || [])[0]))},
      {label: "30일 계좌 플러스 비율", get: (r) => num(pc0((((d.r || {})[r.key] || {}).w30 || [])[2]))},
    ];
    const series = rules.map((r) => ({key: r.key, values: [1, ...((((d.r || {})[r.key]) || {}).curve || [])]}));
    put(body, ui.table(cols, lines), logCurves({series, months: ["시작", ...(d.months || doc.months || [])], height: 180,
      label: `${c.s} ${fmt.tfKo(c.tf)} 규칙별 잔고`}), legend(rules),
    h("p", {class: "an-note"}, `5년 경로 거래 ${fmt.int(d.trades || 0)}건 (30일 계좌로 돈 v4 경로).`, " ", ui.smallSample(d.trades || 0, 20)),
    ui.assume("closed", ASSUME_5Y));
  })();
  return body;
}

function listCard(doc, env) {
  const cells = (doc.cells || []).slice();
  const K = doc.m_keys;
  const opened = new Set(), cache = new Map();
  const full = (c, r) => mrow(((c.r || {})[r] || {}).full, K);
  const pg = ui.pager({size: 10, empty: "맞는 칸이 없습니다", row: (c) => {
    const key = c.s + "@" + c.tf, open = opened.has(key);
    const a = full(c, "v4"), b = full(c, "r1");
    const btn = h("button", {class: "sz-row", type: "button", "aria-expanded": String(open), onclick: () => { open ? opened.delete(key) : opened.add(key); pg.rerender(); }},
      ui.acctLabel({kind: "strategy", strategy: c.s, timeframe: c.tf}),
      h("span", {class: "sz-mid num"}, h("span", {class: fmt.tone(a.mult == null ? null : a.mult - 1)}, `v4 ${mx(a.mult)}${a.bust ? " 파산" : ""}`), " → ",
        h("span", {class: fmt.tone(b.mult == null ? null : b.mult - 1)}, `1% ${mx(b.mult)}${b.bust ? " 파산" : ""}`)),
      h("small", {class: "num muted sz-end"}, `낙폭 ${pc0(a.mdd)} → ${pc0(b.mdd)}`, " ", ui.smallSample(c.trades || 0, 20)));
    return h("div", {class: "sz-item", role: "listitem"}, btn, open ? cellDetail(c, doc, env, cache) : null);
  }});
  const tf = dimSeg("sz-ltf", TF_OPTS.map((o) => (o.id === "all" ? {...o, label: "전체"} : o)), "all", () => apply(), true);
  const sort = dimSeg("sz-sort", [{id: "v4", label: "v4 배수 순"}, {id: "gain", label: "1%로 바꾸면 차이 큰 순"}, {id: "name", label: "이름 순"}], "v4", () => apply(), true);
  function apply() {
    const t = tf.get(), o = sort.get();
    const rows = cells.filter((c) => t === "all" || c.tf === t);
    const m = (c, r) => full(c, r).mult ?? 0;
    rows.sort(o === "name" ? (x, y) => (x.s < y.s ? -1 : x.s > y.s ? 1 : x.tf < y.tf ? -1 : 1)
      : o === "gain" ? (x, y) => (m(y, "r1") - m(y, "v4")) - (m(x, "r1") - m(x, "v4")) : (x, y) => m(y, "v4") - m(x, "v4"));
    pg.set(rows);
  }
  apply();
  return ui.card({plate: "매매법마다", sub: "칸을 누르면 그 칸의 규칙별 표와 곡선"}, h("div", {class: "sz-filters"}, tf.el, sort.el), pg.el,
    ui.assume("closed", ASSUME_5Y));
}

function caveatCard(doc) {
  const a = doc.account || {};
  return ui.card({plate: "먼저 읽어 주세요", cls: "sz-caveat"},
    h("p", {class: "an-warn"}, ui.pill("설명용, 판정 아님", "ref"), " 지금 도는 모의 계좌의 크기 규칙(v4)은 첫 판정 전에 이 결과로 바뀌지 않습니다."),
    h("ul", {class: "sz-list"},
      h("li", null, "36개는 같은 5년 자료로 골라진 매매법이라, 5년 숫자는 원래 좋게 보이는 쪽으로 치우칩니다. 여기서는 규칙끼리의 차이만 봐 주세요."),
      h("li", null, "모든 규칙이 같은 진입·같은 청산 가격을 씁니다. 실제로는 배수가 바뀌면 익절 잠금 가격(증거금 대비 %로 정해짐)도 바뀌는데, 크기 효과만 보려고 청산을 고정했습니다."),
      h("li", null, `손절 한 번 = 잔고 0.5·1·2% 규칙: 첫 손절에 닿으면 (수수료·슬리피지 포함) 그만큼 잃도록 수량을 정합니다. 배수는 v4 후보 중 거래소 한도와 '손절이 강제청산가 안쪽' 확인을 통과하는 것, 증거금은 잔고의 ${pc0(a.margin_cap ?? 0.5)}까지.`),
      h("li", null, "배수 절반: v4 후보마다 배수만 절반 (50→25, 40→20, 30→15, 20→10배), 증거금 비율은 그대로."),
      h("li", null, `좋은 자리 여부는 v4 비율대로 무작위로 정했습니다. 잔고가 $${fmt.int(a.bust_below ?? 10)} 아래로 가면 그 계좌는 멈춥니다(파산). 규칙과 숫자는 결과를 보기 전에 ${doc.prereg || "docs/size5y.md"}에 적어 두었습니다.`)));
}

function readingCard(doc) {
  const box = h("div", {class: "sz-read"});
  const tf = dimSeg("sz-rtf", TF_OPTS, "all", () => draw(), true);
  function draw() {
    const lines = reading(doc, tf.get());
    put(box, ...(lines.length ? lines.map((l, i) => h(i ? "p" : "h2", {class: i ? "sz-say" : "sz-big"}, l)) : [h("p", {class: "muted"}, "숫자가 없습니다.")]));
  }
  draw();
  return ui.card({plate: "쉬운 말로", sub: "숫자는 아래 표와 같은 파일에서"}, h("div", {class: "sz-filters"}, tf.el), box, ui.assume("closed", ASSUME_5Y));
}

// ---------------------------------------------------------------- 손실 크기 규칙 (/api/v4/size5y)
export function size(d, env) {
  const a = d.account || {};
  const n = (d.cells || []).length;
  const out = [viewHead({plate: "손실 크기 규칙", q: "손절 한 번에 잃는 크기를 줄였다면, 5년 동안 무엇이 달라졌을까?",
    meta: `5년 과거 시험 · 기존 36 × 15분·30분·1시간·4시간 = ${fmt.int(n)}칸 · 칸마다 $${fmt.int(a.initial ?? 5000)} 계좌`, at: d.generated_at,
    read: "같은 진입과 같은 청산에 크기만 바꿔 다섯 규칙을 나란히 놓았습니다: 지금 v4, 손절 한 번 = 잔고 0.5% · 1% · 2%, 배수 절반. 표는 규칙이 열, 곡선은 규칙마다 한 줄입니다."})];
  if (d.unavailable) { out.push(ui.card({plate: "손실 크기 규칙"}, h("p", {class: "muted"}, d.note || "준비 중입니다."))); return out; }
  const par = d.parity || {};
  out.push(caveatCard(d), readingCard(d), compareCard(d, env), curvesCard(d), listCard(d, env),
    h("p", {class: "an-note an-foot"}, `손실 크기 규칙: 기존 36 · 5년 과거 시험 · ${d.label || "설명용, 판정 아님"} · 사전 등록 ${d.prereg || "docs/size5y.md"}`,
      par.windows ? ` · 엔진 맞춰 보기: 30일 계좌 ${fmt.int(par.windows)}개에서 v4 다시 계산 = 엔진 (차이 최대 $${fmt.num(par.max_diff || 0, 2)})` : ""));
  return out;
}

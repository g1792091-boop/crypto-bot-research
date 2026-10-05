// 분석 › 비용 (wave 2 part B, ranked #8): where the money leaks. /api/v4/costs (dash/more/costs.py).
//   1. 돈이 새는 곳: a waterfall 수수료 전 → 수수료 → 펀딩 → 실제 for the groups shown with money (기존 36 / 5분봉 / 추가 계좌)
//   2. 거래 한 번에: every group per trade as a share of its margin, the coin flips always right under the strategies
//      (DeepSeek and the coin flips: these ratios only, never a money sum: owners' D10 / D11)
//   3. 봉별: the 36 vs their same-bar coin flips per timeframe (참고)
//   4. 실제 호가였다면 (추정): stop slippage of SL / LOCK / LIQ exits and the order-book cost vs the paper's 0.02 %
// Every number is the paper's own calculation (fees, funding) or an estimate from records (slippage): it says so.
import {h, s, ui, fmt, local} from "../core/pb.js";
import {viewHead, thin} from "./analysis-kit.js";

const KO = {core: "기존 36", flip_same: "동전 봇 (같은 봉)", ds200: "딥시크", reel: "5분봉 단타", flip5: "5분봉 동전 봇 3개", extra: "추가 계좌"};
const MONEY = ["core", "reel", "extra"];
const ROWS = ["core", "flip_same", "ds200", "reel", "flip5", "extra"];
const FLIP = new Set(["flip_same", "flip5"]);
const bps = (x) => (x == null ? "—" : `${fmt.num(x, x < 10 ? 1 : 0)}bp`);
const est = () => ui.pill("추정", "thin", "기록으로 낸 추정입니다. 모의 체결은 바뀌지 않습니다.");

/** The view (analysis.js VIEWS render): d = /api/v4/costs. */
export function costs(d, env) {
  const g = (d && d.groups) || {};
  const core = g.core || {};
  const out = [viewHead({plate: "비용 점검", q: "수수료와 펀딩이 얼마나 깎아 먹나?",
    meta: `닫힌 거래 ${fmt.int(Object.values(g).reduce((a, x) => a + (x.trades || 0), 0))}건 기준`,
    read: "수수료 전 = 가격이 움직여 번(잃은) 몫, 실제 = 수수료·펀딩까지 뺀 몫입니다. 동전 봇 줄을 늘 바로 아래에 둡니다. 수수료·펀딩은 바이낸스 요율로 계산한 모의 값, 미끄러짐은 기록으로 낸 추정입니다.",
    warn: [thin(core.trades, 30, "기존 36의 닫힌 거래")]})];
  out.push(waterfallCard(d));
  out.push(perTradeCard(d, env));
  out.push(byTfCard(d, env));
  out.push(slipCard(d));
  return out;
}

// ---------------------------------------------------------------- 1. the waterfall (money groups only)
function waterfallCard(d) {
  const g = (d && d.groups) || {};
  const have = MONEY.filter((k) => g[k] && g[k].money && g[k].trades);
  const body = h("div", {class: "an-cost-wf"});
  let pick = have.includes(local.get("an-cost-g")) ? local.get("an-cost-g") : have[0];
  const paint = () => {
    const x = g[pick];
    if (!x) { body.replaceChildren(ui.empty("닫힌 거래가 아직 없습니다")); return; }
    body.replaceChildren(waterfall(x.money), h("p", {class: "an-meta"},
      `${KO[pick]} · 계좌 ${fmt.int(x.accounts)}개 · 거래 ${fmt.int(x.trades)}건 · 강제청산 ${fmt.int(x.liq)}건`));
  };
  const seg = have.length > 1 ? ui.seg(have.map((k) => ({id: k, label: KO[k]})), pick, (id) => { pick = id; local.set("an-cost-g", id); paint(); }, {label: "묶음"}) : null;
  paint();
  return ui.card({plate: "돈이 새는 곳", sub: "수수료 전 → 수수료 → 펀딩 → 실제"}, seg, body,
    h("p", {class: "an-note"}, "딥시크·동전 봇은 돈 합계를 보여 주지 않고 아래 '거래 한 번에'에서 비율로만 셉니다."),
    ui.assume(null, "USDT 합계 · 닫힌 거래"));
}

/** A four-step waterfall (SVG, drawn at a fixed viewBox and scaled to the card). m = {before, fees, funding, after}. */
export function waterfall(m) {
  const W = 320, H = 150, top = 18, bot = 26, colW = W / 4;
  const steps = [
    {k: "수수료 전", from: 0, to: m.before, tone: m.before >= 0 ? "up" : "down"},
    {k: "수수료", from: m.before, to: m.before - m.fees, tone: "cost"},
    {k: "펀딩", from: m.before - m.fees, to: m.after, tone: m.funding > 0 ? "cost" : m.funding < 0 ? "up" : "flat"},
    {k: "실제", from: 0, to: m.after, tone: m.after >= 0 ? "up" : "down"},
  ];
  const vals = steps.flatMap((x) => [x.from, x.to]);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals), span = hi - lo || 1;
  const Y = (v) => top + (H - top - bot) * (hi - v) / span;
  const lab = [fmt.money(m.before, true), fmt.money(-m.fees, true), fmt.money(-m.funding, true), fmt.money(m.after, true)];
  const kids = [s("line", {x1: 0, x2: W, y1: Y(0).toFixed(1), y2: Y(0).toFixed(1), class: "an-cost-zero"})];
  steps.forEach((x, i) => {
    const y1 = Y(Math.max(x.from, x.to)), y2 = Y(Math.min(x.from, x.to));
    const x0 = i * colW + colW * 0.2;
    kids.push(s("rect", {x: x0.toFixed(1), y: y1.toFixed(1), width: (colW * 0.6).toFixed(1), height: Math.max(1.5, y2 - y1).toFixed(1),
      class: `an-cost-bar ${x.tone}`}));
    if (i < 3) kids.push(s("line", {x1: (x0 + colW * 0.6).toFixed(1), x2: ((i + 1) * colW + colW * 0.2).toFixed(1),
      y1: Y(x.to).toFixed(1), y2: Y(x.to).toFixed(1), class: "an-cost-link"}));
    kids.push(s("text", {x: (i * colW + colW / 2).toFixed(1), y: Math.max(12, y1 - 5).toFixed(1), class: "an-cost-val", "text-anchor": "middle"}, lab[i]));
    kids.push(s("text", {x: (i * colW + colW / 2).toFixed(1), y: H - 8, class: "an-cost-lab", "text-anchor": "middle"}, x.k));
  });
  return s("svg", {viewBox: `0 0 ${W} ${H}`, class: "an-cost-svg", role: "img",
    "aria-label": `수수료 전 ${lab[0]}, 수수료 ${lab[1]}, 펀딩 ${lab[2]}, 실제 ${lab[3]} USDT`}, kids);
}

// ---------------------------------------------------------------- 2. per trade, every group (coin flips beside)
function perTradeCard(d, env) {
  const g = (d && d.groups) || {};
  const rows = ROWS.filter((k) => g[k] && g[k].trades);
  if (!rows.length) return ui.card({plate: "거래 한 번에", sub: "증거금 대비"}, ui.empty("닫힌 거래가 아직 없습니다"));
  const maxFee = Math.max(...rows.map((k) => (g[k].per_trade && g[k].per_trade.fees) || 0), 1e-9);
  const row = (k) => {
    const x = g[k], p = x.per_trade || {};
    // coin flips are the yardstick: their own numbers stay neutral (no up / down colour next to the strategies)
    const tone = (v) => (FLIP.has(k) ? "ink2" : fmt.tone(v));
    return h("div", {class: ["an-cost-row", FLIP.has(k) ? "flip" : ""], role: "listitem"},
      h("b", {class: "an-cost-k"}, KO[k], h("small", null, ` ${fmt.int(x.trades)}건`), x.trades < 20 ? [" ", ui.smallSample(x.trades, 20)] : null),
      h("span", {class: "an-cost-nums"},
        h("span", null, h("i", null, "수수료 전 "), h("b", {class: ["num", tone(p.before)]}, fmt.pct(p.before, 2))),
        h("span", null, h("i", null, "수수료 "), h("b", {class: ["num", FLIP.has(k) ? "ink2" : "down"]}, fmt.pct(-p.fees, 2))),
        h("span", null, h("i", null, "펀딩 "), h("b", {class: "num"}, fmt.pct(-p.funding, 2))),
        h("span", null, h("i", null, "실제 "), h("b", {class: ["num", tone(p.after)]}, fmt.pct(p.after, 2)))),
      h("span", {class: "an-cost-feebar", "aria-hidden": "true"}, h("i", {style: {"--w": `${Math.round(100 * (p.fees || 0) / maxFee)}%`}})));
  };
  return ui.card({plate: "거래 한 번에", sub: "증거금 대비 평균 · 참고"}, h("div", {class: "an-cost-rows", role: "list"}, rows.map(row)),
    h("p", {class: "an-note"}, "막대 = 거래 한 번의 수수료 크기. 증거금 대비 비율이라 묶음끼리 바로 견줄 수 있습니다. 30배 거래 한 번의 수수료는 증거금의 약 3%입니다."),
    ui.refNote(env && env.verdictTs, "동전 봇은 비교 기준입니다."), ui.assume());
}

// ---------------------------------------------------------------- 3. by timeframe: the 36 vs same-bar coin flips
function byTfCard(d, env) {
  const t = (d && d.by_tf) || {};
  const tfs = ["15m", "30m", "1h", "4h"].filter((tf) => (t.core && t.core[tf]) || (t.flip_same && t.flip_same[tf]));
  if (!tfs.length) return ui.card({plate: "봉별", sub: "기존 36 vs 같은 봉 동전 봇"}, ui.empty("닫힌 거래가 아직 없습니다"));
  const v = (c, key) => (c && c.per_trade ? c.per_trade[key] : null);
  const cellOf = (c, key, flip) => (c && c.trades ? h("b", {class: ["num", flip ? "ink2" : key === "fees" ? "down" : fmt.tone(v(c, key))]},
    fmt.pct(key === "fees" ? -v(c, key) : v(c, key), 2)) : "—");
  return ui.card({plate: "봉별", sub: "기존 36 vs 같은 봉 동전 봇 · 거래당 · 참고"}, ui.table([
    {label: "봉", l: true, get: (tf) => fmt.tfKo(tf)},
    {label: "36 수수료 전", get: (tf) => cellOf(t.core && t.core[tf], "before")},
    {label: "36 수수료", get: (tf) => cellOf(t.core && t.core[tf], "fees")},
    {label: "36 실제", get: (tf) => cellOf(t.core && t.core[tf], "after")},
    {label: "동전 실제", get: (tf) => cellOf(t.flip_same && t.flip_same[tf], "after", true)},
    {label: "거래 (36 / 동전)", get: (tf) => `${fmt.int((t.core && t.core[tf] && t.core[tf].trades) || 0)} / ${fmt.int((t.flip_same && t.flip_same[tf] && t.flip_same[tf].trades) || 0)}`},
  ], tfs), ui.refNote(env && env.verdictTs), ui.assume());
}

// ---------------------------------------------------------------- 4. real quotes (추정)
function slipCard(d) {
  const st = (d && d.stops) || {}, bk = (d && d.book) || {};
  const paper = st.paper_assume_bps ?? bk.paper_assume_bps ?? 2;
  const kids = [];
  if (st.ready && st.estimated) {
    const scale = Math.max(paper, st.real_p90_bps || 0, st.real_median_bps || 0, 1);
    kids.push(h("h3", {class: "an-cost-h"}, "손절이 진짜 주문이었다면 ", est()),
      bars([["모의 가정", paper, "paper"], ["실제 추정 (중간)", st.real_median_bps, "real"], ["10번 중 9번째", st.real_p90_bps, "real"]], scale),
      h("p", {class: "an-meta"}, `손절·잠금·강제청산 청산 ${fmt.int(st.exits)}건 중 추정 ${fmt.int(st.estimated)}건 · 모의보다 나빴던 청산 ${fmt.int(st.worse_than_paper)}건`
        + (st.extra_cost_main_usd != null ? ` · 기존 36·5분봉·추가 계좌가 더 잃었을 돈 약 ${fmt.money(st.extra_cost_main_usd)} USDT (추정)` : "")));
  } else {
    kids.push(h("h3", {class: "an-cost-h"}, "손절이 진짜 주문이었다면 ", est()), ui.notYet(st.note ? "기록 전" : "수집 전", st.note), h("p", {class: "an-meta"}, st.note || "밤 점검이 손절 청산을 공개 체결 기록으로 다시 계산하면 생깁니다."));
  }
  const ev = bk.by_event || {};
  const evs = Object.keys(ev);
  kids.push(h("h3", {class: "an-cost-h"}, "호가창으로 본 진입·청산 비용 ", est()));
  if (bk.ready && evs.length) {
    const scale = Math.max(paper, ...evs.map((k) => ev[k].p90_bps || 0), 1);
    kids.push(bars([["모의 가정", paper, "paper"], ...evs.flatMap((k) => [[`${evKo(k)} 중간`, ev[k].median_bps, "real"], [`${evKo(k)} 10번 중 9번째`, ev[k].p90_bps, "real"]])], scale),
      h("p", {class: "an-meta"}, `호가창 기록 ${fmt.int(bk.reads)}건 · ` + evs.map((k) => `${evKo(k)} ${fmt.int(ev[k].n)}건 중 모의 가정보다 큼 ${fmt.int(ev[k].over_paper)}건`).join(" · ")));
  } else {
    kids.push(ui.notYet(bk.note ? "기록 전" : "수집 전", bk.note), h("p", {class: "an-meta"}, bk.note || "봇이 진입·청산 때 호가창을 읽어 기록하면 생깁니다."));
  }
  return ui.card({plate: "실제 호가였다면", sub: `추정 · 모의는 ${bps(paper)} 미끄러짐을 가정`}, ...kids,
    h("p", {class: "an-note"}, "1bp = 0.01%. 손절가(또는 최우선 호가)보다 불리하게 체결됐을 몫입니다. 기록일 뿐 모의 체결은 바뀌지 않습니다."));
}
const evKo = (k) => ({entry: "진입", exit: "청산"}[k] || String(k));

/** Horizontal bars [label, bp, "paper"|"real"] on one scale. */
function bars(items, scale) {
  return h("div", {class: "an-cost-bars", role: "list"}, items.map(([k, v, cls]) => h("div", {class: "an-cost-brow", role: "listitem"},
    h("span", {class: "k"}, k), h("span", {class: ["t", cls]}, h("i", {style: {"--w": `${v == null ? 0 : Math.max(1, Math.min(100, 100 * v / scale))}%`}})),
    h("b", {class: "num"}, bps(v)))));
}

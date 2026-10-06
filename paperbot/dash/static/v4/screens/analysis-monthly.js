// 분석 › 5년 월별 (combo-5y): per strategy of the 기존 36, the 5-year distribution of a month's result (GET
// /api/v4/combo5y/monthly, dash/more/combo5y.py: every KST month 2021-08..2026-09 a fresh $5,000 account per timeframe,
// the v4 rules) and where the paper run so far sits among the 5-year months cut at the same number of days (closed
// trades on both sides). Day 0-1: the strip still shows the 5 years; the paper mark carries 표본 적음 and the waiting
// bars say how far the run is. 설명용, 판정 아님; the 36 were chosen on these 5 years (selection bias, said up front).
// Its look: analysis-monthly.css (@imported by analysis.css).
import {h, s, ui, fmt, local} from "../core/pb.js";
import {viewHead, waitCard} from "./analysis-kit.js";

const SORTS = [{id: "median", label: "5년 중앙값 순"}, {id: "now", label: "지금 위치 순"}, {id: "name", label: "이름 순"}];
const TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"};


/** One strip: a thin tick per 5-year month (its value after the same days, or the full month), the median, and the
 *  paper run so far as the thick accent mark. Vector strokes keep their width when the strip stretches. */
function strip(vals, mark, lo, hi) {
  const X = (v) => (100 * (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo));
  const kids = [s("line", {class: "am-zero", x1: X(0).toFixed(2), x2: X(0).toFixed(2), y1: 0, y2: 24, "vector-effect": "non-scaling-stroke"})];
  for (const v of vals) if (v != null) kids.push(s("line", {class: ["am-tick", v > 0 ? "up" : v < 0 ? "down" : ""], x1: X(v).toFixed(2), x2: X(v).toFixed(2), y1: 5, y2: 19, "vector-effect": "non-scaling-stroke"}));
  const sorted = vals.filter((v) => v != null).sort((a, b) => a - b);
  if (sorted.length) {
    const med = sorted[Math.floor(sorted.length / 2)];
    kids.push(s("line", {class: "am-med", x1: X(med).toFixed(2), x2: X(med).toFixed(2), y1: 2, y2: 22, "vector-effect": "non-scaling-stroke"}));
  }
  if (mark != null) kids.push(s("line", {class: "am-now", x1: X(mark).toFixed(2), x2: X(mark).toFixed(2), y1: 0, y2: 24, "vector-effect": "non-scaling-stroke"}));
  return s("svg", {class: "am-strip", viewBox: "0 0 100 24", preserveAspectRatio: "none", "aria-hidden": "true"}, kids);
}

/** 62 monthly bars (gain up, loss down) of one strategy (the 4 timeframes together). */
function bars(m) {
  const v = m.map((x) => (x == null ? 0 : x));
  const top = Math.max(0.05, ...v), bot = Math.min(-0.05, ...v);
  const H = 60, Y = (x) => H * (top - x) / (top - bot), w = 100 / Math.max(1, v.length);
  const kids = [s("line", {class: "am-zero", x1: 0, x2: 100, y1: Y(0).toFixed(2), y2: Y(0).toFixed(2), "vector-effect": "non-scaling-stroke"})];
  v.forEach((x, i) => {
    const y0 = Y(Math.max(0, x)), y1 = Y(Math.min(0, x));
    kids.push(s("rect", {class: ["am-bar", x > 0 ? "up" : x < 0 ? "down" : ""], x: (i * w + w * 0.15).toFixed(2), width: (w * 0.7).toFixed(2), y: y0.toFixed(2), height: Math.max(0.3, y1 - y0).toFixed(2)}));
  });
  return s("svg", {class: "am-bars", viewBox: `0 0 100 ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": "5년 달마다 수익률"}, kids);
}

export function monthly5y(d, env) {
  const rows = d.rows || [];
  const months = d.months || [];
  const day = d.day;
  const hasPaper = rows.some((r) => r.paper);
  const smallN = d.small_n || 20;
  const meth = d.methods || {};
  const out = [viewHead({plate: "5년 월별", q: "한 달에 얼마나 벌고 잃었나 · 지난 5년 달들과 지금",
    meta: [`${months[0] || ""} ~ ${months[months.length - 1] || ""} · ${fmt.int(months.length)}달`, "매달 계좌마다 $5,000로 새로 시작 (v4 규칙)",
      day ? `지금 실험 ${fmt.num(d.elapsed_days, 1)}일째` : "지금 실험 기록 없음", d.label].filter(Boolean).join(" · "),
    at: d.generated ? Date.parse(d.generated) : null,
    read: "줄 하나 = 매매법 하나 (봉 4개 계좌 합, $20,000). 가는 눈금 하나 = 5년 중 한 달" + (day ? `을 지금과 같은 ${fmt.int(day)}일째까지 자른 결과` : "의 결과") + ", 회색 굵은 눈금 = 그 가운데(중앙값), 청록 굵은 눈금 = 지금 실험이 시작한 뒤 지금까지 (닫힌 거래만). 순위 = 그 달들 사이에서 몇 번째.",
    warn: [meth.caveat || "이 36개는 바로 이 5년 자료를 보고 고른 매매법이라 5년 숫자는 실제보다 좋게 나오기 쉽습니다.",
      day && day < 30 ? `지금 실험은 ${fmt.int(day)}일째입니다. 한 달 전체와 비교하지 않고, 5년 달들도 ${fmt.int(day)}일째까지만 잘라서 비교합니다. 며칠 사이의 순위는 거의 우연입니다.` : null,
      d.over_month ? `지금 실험이 한 달(31일)을 넘었습니다. 5년 쪽은 한 달짜리라 기간이 다릅니다: 순위는 참고로만 보세요.` : null]})];
  // waiting: how far the month and the trades are (real numbers only)
  if (hasPaper) {
    const withN = rows.filter((r) => r.paper && r.paper.trades >= smallN).length;
    const maxN = Math.max(0, ...rows.map((r) => (r.paper ? r.paper.trades : 0)));
    const bars2 = [
      {label: "한 달(30일) 중 지난 날", share: Math.min(1, (d.elapsed_days || 0) / 30), words: `지금 ${fmt.num(d.elapsed_days, 1)}일째 · 5년 달과 같은 날 수까지 잘라 비교`},
      {label: `매매법마다 닫힌 거래 ${fmt.int(smallN)}건`, share: rows.length ? withN / rows.length : 0,
        words: `${fmt.int(smallN)}건 넘은 매매법 ${fmt.int(withN)}/${fmt.int(rows.length)} · 가장 많은 매매법 ${fmt.int(maxN)}건`},
    ];
    if (bars2.some((b) => b.share < 1)) out.push(waitCard("5년 월별", bars2, null));
  }
  // summary: where the 36 sit, and the coin-flip yardstick (참고)
  const placed = rows.filter((r) => r.paper && r.paper.rank);
  const above = placed.filter((r) => r.paper.same_day_median != null && r.paper.ret > r.paper.same_day_median).length;
  const below = placed.filter((r) => r.paper.same_day_median != null && r.paper.ret < r.paper.same_day_median).length;
  const fu = (d.flips || {}).unit_months || {};
  const medAll = rows.map((r) => r.median).filter((x) => x != null).sort((a, b) => a - b);
  out.push(ui.card({plate: "한눈에", sub: "기존 36 · 5년 한 달"},
    h("div", {class: "stats s4"},
      ui.stat("5년 한 달 중앙값", medAll.length ? fmt.pct(medAll[Math.floor(medAll.length / 2)], 1) : "—", "36개 매매법 중앙값들의 가운데"),
      ui.stat("이긴 달 비율", fmt.pct(rows.length ? rows.reduce((a, r) => a + (r.pos_share || 0), 0) / rows.length : null, 0, false), "36개 평균"),
      ui.stat("지금 > 같은 날 중앙값", hasPaper ? `${fmt.int(above)}개` : "—", hasPaper ? `아래 ${fmt.int(below)}개 · 같음 ${fmt.int(placed.length - above - below)}개` : "지금 실험 기록 없음"),
      ui.stat("동전 봇 묶음 한 달", fmt.pct(fu.median, 1), fu.n ? `중앙값 · 이긴 달 ${fmt.pct(fu.pos_share, 0, false)} · 참고` : "참고")),
    h("p", {class: "an-note"}, "동전 봇 묶음 = 같은 규칙으로 무작위로 들어가는 봉 4개 계좌의 합. 5년 같은 계산에서 한 달 결과의 가운데입니다."),
    ui.refNote(env.verdictTs, "5년 달과의 비교도 같습니다.")));
  // the list
  let sortBy = local.get("an-m5-sort", "median");
  if (!SORTS.some((x) => x.id === sortBy)) sortBy = "median";
  const pg = ui.pager({size: 8, empty: "매매법이 없습니다", row: (r, i) => rowOf(r, d, i)});
  const order = () => {
    const a = [...rows];
    if (sortBy === "name") a.sort((x, y) => String(x.name).localeCompare(String(y.name), "ko"));
    else if (sortBy === "now") a.sort((x, y) => ((x.paper && x.paper.rank ? x.paper.rank.rank : 999) - (y.paper && y.paper.rank ? y.paper.rank.rank : 999)) || ((y.median || 0) - (x.median || 0)));
    else a.sort((x, y) => (y.median ?? -9) - (x.median ?? -9));
    return a;
  };
  const seg = ui.seg(SORTS, sortBy, (id) => { sortBy = id; local.set("an-m5-sort", id); pg.set(order()); }, {label: "줄 순서"});
  pg.set(order());
  out.push(ui.card({plate: "매매법마다", sub: day ? `눈금 = 5년 달 ${fmt.int(months.length)}개를 ${fmt.int(day)}일째까지` : "눈금 = 5년 달 하나"},
    seg, h("div", {class: "am-legend"}, h("span", null, h("i", {class: "sw tick"}), "5년 한 달"), h("span", null, h("i", {class: "sw med"}), "그 가운데"),
      h("span", null, h("i", {class: "sw now"}), "지금 실험")),
    pg.el,
    ui.assume("closed", "5년 쪽은 과거 계산(매달 $5,000로 새로 시작), 지금 쪽은 시작 뒤 닫힌 거래만")));
  return out;
}

function rowOf(r, d, i) {
  const p = r.paper;
  const vals = p && p.same_day && p.same_day.length ? p.same_day : (r.m || []);
  const mark = p ? p.ret : null;
  const all = [...vals.filter((v) => v != null), mark].filter((v) => v != null);
  const lo = Math.min(-0.1, ...all), hi = Math.max(0.1, ...all);
  const words = !p ? h("span", {class: "muted"}, "지금 기록 없음")
    : [h("b", {class: ["num", fmt.tone(p.ret)]}, fmt.pct(p.ret, 1)), p.rank ? h("span", {class: "am-rank"}, ` ${fmt.int(p.rank.rank)}/${fmt.int(p.rank.of)}`) : null];
  const tfs = Object.entries(r.tfs || {});
  const detail = h("div", {class: "stack tight am-detail"},
    h("p", {class: "am-sub"}, "5년 달마다 (봉 4개 합, 자금 $20,000 대비)"),
    bars(r.m || []),
    h("div", {class: "am-axis"}, h("span", null, (d.months || [])[0] || ""), h("span", null, (d.months || [])[(d.months || []).length - 1] || "")),
    ui.table([
      {label: "봉", l: true, get: ([tf]) => TF_KO[tf] || tf},
      {label: "한 달 중앙값", get: ([, t]) => fmt.pct(t.median, 1)},
      {label: "이긴 달", get: ([, t]) => fmt.pct(t.pos_share, 0, false)},
      {label: "가장 좋은 달", get: ([, t]) => fmt.pct(t.best, 0)},
      {label: "가장 나쁜 달", get: ([, t]) => fmt.pct(t.worst, 0)},
      {label: "파산한 달", get: ([, t]) => fmt.int(t.bust_months)},
      {label: "5년 한 계좌", get: ([, t]) => (t.one ? `${fmt.num(t.one.multiple, 2)}배${t.one.bust ? " · 파산" : ""}` : "—")},
    ], tfs),
    h("p", {class: "an-note"}, `5년 한 계좌 = 같은 계좌를 끊지 않고 5년 굴렸다면 처음 $5,000의 몇 배 (파산하면 거기서 멈춤). 거래 ${fmt.int(r.trades)}건 · 이긴 거래 ${fmt.pct(r.win_rate, 0, false)} · 강제청산 ${fmt.int(r.liq)}건 (62달 합계).`));
  return h("div", {class: "lrow an-row am-row", role: "listitem"},
    h("span", {class: "rk"}, `${fmt.int(i + 1)}`),
    h("span", {class: "lname an-wrap"}, r.name),
    h("span", {class: "ret"}, words),
    h("div", {class: "am-stripbox"}, strip(vals, mark, lo, hi),
      h("div", {class: "am-scale"}, h("span", null, fmt.pct(lo, 0)), h("span", null, "0"), h("span", null, fmt.pct(hi, 0)))),
    h("span", {class: "meta"},
      p && p.small ? ui.pill("표본 적음", "thin", `지금 닫힌 거래 ${p.trades}건`) : null,
      r.trades === 0 ? ui.pill("5년 동안 거래 없음", "thin") : r.trades != null && r.trades < 62 ? ui.pill(`5년 거래 ${fmt.int(r.trades)}건뿐`, "thin") : null,
      h("span", null, `5년 한 달 중앙값 ${fmt.pct(r.median, 1)}`), h("span", null, `이긴 달 ${fmt.pct(r.pos_share, 0, false)}`),
      h("span", null, `좋은 달 ${fmt.pct(r.best, 0)} · 나쁜 달 ${fmt.pct(r.worst, 0)}`),
      p ? h("span", null, `지금 닫힌 거래 ${fmt.int(p.trades)}건${p.rank ? ` · 같은 날 5년 달 중 ${fmt.int(p.rank.below)}개보다 위` : ""}`) : null),
    h("div", {class: "am-more"}, ui.disclosure("봉마다 · 달마다 보기", detail)));
}


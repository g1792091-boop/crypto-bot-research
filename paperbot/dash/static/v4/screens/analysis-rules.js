// 분석: 좋은 자리 vs 보통 / 그림자 비교 / 계좌 겹침 / 조합 시너지 / GH Coin / 45개 질문 (builder C; old analysis.js
// rLevrule / rShadows / rSynergy / rQuestions, app.js renderOverlap, ghcoin.js).
// HONESTY: before the checkpoint verdict (or levrule's own decision) no p-values, no ✓ / ✕ and no "passes" words: the
// numbers are '중간 숫자' with refNote. Shadow curves come from the server only; with none it says 수집 전.
import {h, put, ui, fmt, motion, makeChart, tok} from "../core/pb.js";
import {viewHead, thin, dimSeg, acctLabel} from "./analysis-kit.js";
import {limitEntry} from "./analysis-limit.js";
import {driftCard} from "./analysis-drift.js";

const GKO = {best: "좋은 자리", normal: "보통"};
const rp = (x) => (x == null ? "—" : `${fmt.num(x * 100, 3, true)}%`);       // per unit of exposure, small numbers

// ---------------------------------------------------------------- 좋은 자리 vs 보통 (/api/analysis/levrule)
export function levrule(d, env) {
  if (d.status === "no_run") return [viewHead({plate: "좋은 자리 vs 보통", q: "좋은 자리에서 배수를 높인 게 나았나", read: d.status_ko || "아직 계좌가 없습니다."})];
  const g = d.groups || {}, b = g.best || {}, n = g.normal || {}, c = d.cells || {}, tr = d.trades || {};
  const decided = d.status === "decided";
  const out = [viewHead({plate: "좋은 자리 vs 보통", q: "좋은 자리에서 배수를 높인 게 나았나 (레버리지 규칙 B)",
    meta: `기존 36 매매법 거래 ${fmt.int(tr.strategy || 0)}건 · 동전 봇 ${fmt.int(tr.coin_flips || 0)}건`, at: d.computed_at, stale: d.stale,
    read: "좋은 자리는 50배·50%부터, 보통 자리는 30배·30%부터 시도합니다. 배수가 다른 거래를 같은 크기로 맞추려고 '노출 1단위당 수익'(= ROE ÷ 레버리지, 비용 뺀 순)으로 비교합니다.",
    warn: [decided ? h("p", {class: "an-read"}, h("b", null, d.status_ko || "판정 끝"), " · 미리 정한 방법 그대로의 코드 판정입니다. 다음 창은 규칙 버전에 따라 새 계좌로, 두 분이 확인합니다.")
      : h("p", {class: "an-warn"}, h("b", null, "30일 판정 전 결론 없음. "), "아래는 중간 숫자입니다. 규칙 B는 첫 판정(30일째)에 미리 정한 방법으로 한 번만 판정하고, 그 전에는 아무것도 바꾸지 않습니다.")]})];
  out.push(ui.card({plate: "중간 숫자", sub: decided ? "판정에 쓴 숫자" : "참고"},
    h("div", {class: "stats s4"},
      ui.stat("매매법: 좋은 자리 − 보통", h("b", {class: fmt.tone(d.d_s)}, rp(d.d_s)), `노출 1단위당 · 적격 칸 ${fmt.int(c.strategy_eligible || 0)}/${fmt.int(c.strategy_total || 0)}`),
      ui.stat("동전 봇: 좋은 자리 − 보통", h("b", null, rp(d.d_c)), `같은 구분의 우연 기준 · 적격 칸 ${fmt.int(c.coin_flips_eligible || 0)}/${fmt.int(c.coin_flips_total || 0)}`),
      decided ? ui.stat("한쪽 p (매매법)", d.p_s == null ? "—" : fmt.num(d.p_s, 3), `기준 ≤ ${fmt.num((d.conditions || {}).alpha, 2)}`) : null,
      decided ? ui.stat("조건", `(가) ${(d.conditions || {}).a_best_beats_normal ? "충족" : "아님"} · (나) ${(d.conditions || {}).b_beats_coin_flips ? "충족" : "아님"}`, "(가) 좋은 자리가 낫고 p ≤ 0.10 · (나) 동전 봇 차이보다 큼") : null),
    decided ? null : ui.refNote(env.verdictTs)));
  // two small tables (매매법, then 동전 봇 as 참고): three narrow columns each, readable on a phone
  const M = [["거래", (x) => fmt.int(x.trades)], ["승률", (x) => fmt.pct(x.win_rate, 0, false)],
    ["평균 ROE", (x) => h("span", {class: fmt.tone(x.mean_roe)}, fmt.pct(x.mean_roe))],
    ["거래당 자금 대비", (x) => h("span", {class: fmt.tone(x.mean_eq)}, fmt.pct(x.mean_eq, 2))],
    ["노출 1단위당", (x) => h("b", {class: fmt.tone(x.mean_r)}, rp(x.mean_r))]];
  const pair = (bx, nx) => ui.table([{label: "", l: true, get: (m) => m[0]},
    {label: "좋은 자리", get: (m) => (bx && bx.trades ? m[1](bx) : "—")}, {label: "보통", get: (m) => (nx && nx.trades ? m[1](nx) : "—")}], M);
  out.push(ui.card({plate: "묶음별 숫자"},
    h("h3", {class: "an-sub"}, "매매법 계좌"), pair(b.strategy, n.strategy),
    h("h3", {class: "an-sub"}, "동전 봇 (같은 구분, 참고)"), pair(b.coin_flips, n.coin_flips),
    h("p", {class: "an-note"}, "노출 1단위당 수익 = 손익 ÷ (증거금 × 레버리지) = ROE ÷ 레버리지 (수수료·펀딩 뺀 순).")));
  const mix = d.leverage_mix || {}, rk = d.reason_ko || {};
  const mixRows = ["best", "normal"].map((k) => {
    const m = mix[k] || {}, bl = m.by_leverage || {}, wl = m.why_lower || {};
    const tot = Object.values(bl).reduce((a, x) => a + x, 0);
    const rw = (g[k] || {}).coin_flips_at_strategy_mix || {};
    return {k, bl, wl, tot, rw};
  });
  out.push(ui.card({plate: "실제로 들어간 배수와 이유", sub: "매매법 계좌"},
    h("div", {class: "an-mix", role: "list"}, mixRows.map((r) => h("div", {class: "an-mixrow", role: "listitem"},
      h("b", null, GKO[r.k], h("span", {class: "muted"}, ` ${fmt.int(r.tot)}건`)),
      h("div", {class: "an-mixcells"}, ["50", "40", "30", "20"].filter((lv) => r.bl[lv]).map((lv) => {
        const why = Object.entries(r.wl[lv] || {}).map(([code, v]) => `${rk[code] || code} ${fmt.int(v)}`).join(", ");
        return h("span", {class: "an-mixcell"}, h("b", null, fmt.lev(Number(lv))), ` ${fmt.int(r.bl[lv])}건 (${fmt.pct(r.bl[lv] / (r.tot || 1), 0, false)})`,
          why ? h("span", {class: "an-why"}, `왜 낮게: ${why}`) : null);
      })),
      r.rw.mean_r != null ? h("p", {class: "an-note"}, `동전 봇을 같은 배수 비중으로 맞추면: 노출당 ${rp(r.rw.mean_r)} · 자금 대비 ${fmt.pct(r.rw.mean_eq, 2)}${r.rw.coverage < 1 ? ` (맞춘 비율 ${fmt.pct(r.rw.coverage, 0, false)})` : ""} (참고)`) : null))),
    h("p", {class: "an-note"}, "안전 조건(거래소 구간, 손절이 청산가보다 안쪽, 손절 손실 ≤ 자금 15%)에 막히면 한 단계 내려갑니다. '왜 낮게' = 첫 후보를 막은 조건 (진입 기록).")));
  const cr = Object.entries(d.cell_rows || {});
  const pg = ui.pager({size: 10, empty: "아직 두 묶음 모두 10건이 넘은 계좌가 없습니다", row: ([a, r]) => h("a", {class: "lrow click an-row", role: "listitem", href: env.ctx.href("account", a), title: a},
    h("span", {class: "rk"}, "칸"), h("span", {class: "lname"}, acctLabel(a)), h("span", {class: ["ret num", fmt.tone(r[2])]}, rp(r[2])),
    h("span", {class: "meta"}, h("span", null, `좋은 자리 ${fmt.int(r[0])}건`), h("span", null, `보통 ${fmt.int(r[1])}건`)))});
  pg.set(cr);
  out.push(ui.card({plate: "적격 칸", sub: "두 묶음 모두 10건 이상인 계좌 · 오른쪽 = 차이 (노출당)"}, pg.el,
    d.note ? ui.moreText(d.note, 2, "an-note") : null,
    h("p", {class: "an-note"}, h("a", {href: "/api/doc/levrule-eval", target: "_blank", rel: "noopener"}, "미리 정한 방법 원문 (새 탭)"))));
  return out;
}

// ---------------------------------------------------------------- 그림자 비교 (/api/analysis/shadows[?account=])
const CURVE_SETS = {lev: ["base", "lev10", "lev20", "lev30", "lev40", "lev50"], levm: ["base", "lev20m20", "lev30m30", "lev40m40", "lev50m50"]};
const CURVE_KO = {base: "base (실제 규칙)", lev10: "10배", lev20: "20배", lev30: "30배", lev40: "40배", lev50: "50배",
  lev20m20: "20배·20%", lev30m30: "30배·30%", lev40m40: "40배·40%", lev50m50: "50배·50%"};
const CURVE_TOK = ["--accent", "--term-cyan", "--up", "--warn", "--down", "--ink-2"];
export function shadows(d, env) {
  const base = d.base || {};
  const out = [viewHead({plate: "그림자 비교", q: "규칙 하나만 바꿨다면 어땠을까",
    meta: `밤 점검이 다시 돌린 base 그림자 ${fmt.int(base.trades || 0)}건 · 거래당 자금 대비 ${fmt.pct(base.mean_eq, 2)}${d.label ? " · " + d.label : ""}`, at: d.computed_at, stale: d.stale,
    read: "기존 36 매매법의 같은 거래를 규칙 하나만 바꿔 다시 계산합니다. 차이 = 그 그림자 평균 − 같은 거래의 base 평균. 나음·나쁨 = 같은 거래끼리 비교한 비율.",
    warn: [d.error ? d.error : null, thin(base.trades || 0, 30, "base 그림자 거래")]})];
  const groups = d.groups || [];
  if (groups.length) {
    const body = h("div");
    const seg = dimSeg("shadow", groups.map((g) => ({id: g.key, label: g.title})), groups[0].key, () => paint(true), true);
    function paint(anim) {
      const g = groups.find((x) => x.key === seg.get()) || groups[0];
      put(body, ui.table([
        {label: "그림자", l: true, get: (r) => h("span", {class: r.small || !r.trades ? "muted" : ""}, r.ko, " ", ui.smallSample(r.trades || 0, 10))},
        {label: "거래", get: (r) => [fmt.int(r.trades || 0), r.not_entered ? h("span", {class: "muted"}, ` (진입 안 함 ${fmt.int(r.not_entered)})`) : null]},
        {label: "자금 대비", get: (r) => h("span", {class: fmt.tone(r.mean_eq)}, fmt.pct(r.mean_eq, 2))},
        {label: "base와 차이", get: (r) => h("span", {class: fmt.tone(r.vs_base_eq)}, fmt.pct(r.vs_base_eq, 2))},
        {label: "나음 / 나쁨", get: (r) => `${r.better_share == null ? "—" : fmt.pct(r.better_share, 0, false)} / ${r.worse_share == null ? "—" : fmt.pct(r.worse_share, 0, false)}`},
      ], g.rows || []), g.five_year ? ui.moreText(`5년 기준: ${g.five_year}`, 2, "an-note") : null);
      if (anim) motion.swap(body);
    }
    paint(false);
    out.push(ui.card({plate: "규칙별"}, seg.el, body));
  }
  out.push(shadowCurves(d, env));
  { const lim = limitEntry(d); if (lim) out.push(lim); out.push(driftCard(env)); }     // ana8B: entry cost cards
  if (d.note) out.push(h("p", {class: "an-note an-foot"}, d.note));
  return out;
}
function shadowCurves(d, env) {
  const cv = d.curves || {}, acc = cv.account;
  const pick = h("select", {class: "select", "aria-label": "계좌 고르기"}, h("option", {value: ""}, "매매법 계좌 중앙값 (전체)"),
    (d.accounts || []).map((a) => h("option", {value: a}, acctLabel(a))));
  pick.value = env.query.account || "";
  pick.addEventListener("change", () => env.reload(pick.value ? {account: pick.value} : {}));
  const body = h("div", {class: "stack tight"});
  const seg = dimSeg("curveset", [{id: "lev", label: "레버리지 고정 (티어 비중)"}, {id: "levm", label: "레버리지 = 비중"}], "lev", () => paint());
  let chartBox = null;
  async function paint() {
    const vs = (CURVE_SETS[seg.get()] || CURVE_SETS.lev).filter((v) => (cv.variants || []).includes(v));
    if (!(cv.days || []).length || !vs.length) {
      put(body, h("p", {class: "muted"}, "아직 그림자 자금 곡선이 없습니다 (밤 점검이 하루 이상 돈 뒤 생깁니다). "), ui.notYet("곡선 수집 전"));
      return;
    }
    const last = cv.days.length - 1;
    const series = vs.map((v, i) => ({v, i, ys: acc ? ((acc.curves || {})[v] || []) : (((cv.by_variant || {})[v] || {}).median || [])}));
    chartBox = h("div", {class: "an-chart", role: "img", "aria-label": "그림자 자금 곡선"});
    put(body, h("div", {class: "an-legend2"}, series.map((s) => h("span", null, h("i", {style: {background: `var(${CURVE_TOK[s.i % CURVE_TOK.length]})`}}), CURVE_KO[s.v] || s.v))), chartBox,
      ui.table([{label: "그림자", l: true, get: (s) => CURVE_KO[s.v] || s.v},
        {label: `${acc ? "이 계좌" : "중앙값"} (${cv.days[last]})`, get: (s) => fmt.money(s.ys[last])},
        {label: "파산", get: (s) => (acc ? ((acc.bust_day || {})[s.v] ? `파산 ${(acc.bust_day || {})[s.v]}` : "없음") : `${fmt.int((((cv.by_variant || {})[s.v] || {}).busts || [])[last] || 0)} / ${fmt.int(((cv.by_variant || {})[s.v] || {}).accounts || 0)}`)}], series));
    try {
      const C = await makeChart(chartBox);
      env.track(C.dispose);
      const t = cv.days.map((x) => Math.floor(Date.parse(x + "T00:00:00Z") / 1000));
      series.forEach((s, k) => {
        const ln = C.chart.addLineSeries({color: tok(CURVE_TOK[s.i % CURVE_TOK.length]), lineWidth: 2, title: "", lastValueVisible: false, priceLineVisible: false,
          priceFormat: {type: "price", precision: 0, minMove: 1}});
        ln.setData(t.map((x, j) => ({time: x, value: s.ys[j]})).filter((p) => p.value != null));
        if (k === 0) ln.createPriceLine({price: cv.start || 5000, color: tok("--muted"), lineStyle: 2, lineWidth: 1, title: "시작"});
      });
      C.chart.timeScale().fitContent();
    } catch { put(chartBox, ui.errorBox(null)); }
  }
  paint();
  return ui.card({plate: acc ? `레버리지 자금 곡선 · ${acctLabel(acc.account_id)}` : "레버리지 자금 곡선 · 중앙값", acts: [pick]}, seg.el, body,
    h("p", {class: "an-note"}, `같은 거래를 레버리지만 바꿔 ${fmt.money(cv.start || 5000)}부터 굴린 자금. 파산 = ${fmt.money(cv.bust_below || 10)} 아래.`),
    ui.assume(null, "그림자 = 같은 거래를 다시 계산한 가정"));
}

// ---------------------------------------------------------------- 계좌 겹침 (/api/overlap?days=7)
export function overlap(d, env) {
  const r = d.rules || {}, ac = d.accounts || {}, ex = d.exposure, pr = d.pairs;
  const out = [viewHead({plate: "계좌 겹침", q: "계좌들이 사실상 같은 베팅을 하고 있나",
    meta: d.window ? `지난 ${fmt.num(d.window.days, 0)}일 기록 · 비교할 수 있는 매매법 계좌 ${fmt.int(ac.strategy_enough_data)}/${fmt.int(ac.strategy)}개` : "자본 기록 없음", at: d.computed_at,
    read: `계좌끼리 비교는 기록이 충분할 때만 합니다: 같이 쌓인 기록 ${fmt.num(r.min_days, 0)}일 이상, 계좌마다 거래 ${fmt.int(r.min_trades)}번 이상. 동전 봇은 묶지 않고 기준으로만 봅니다. 앞으로도 그렇다는 예측이 아닙니다.`})];
  if (!d.window) { out.push(ui.card({}, ui.empty("아직 자본 기록이 없습니다."))); return out; }
  const groups = d.groups || [];
  out.push(ui.card({plate: "같이 움직이는 계좌", sub: `1시간 수익률 상관 ${fmt.num(r.group_corr, 1)} 이상인 묶음`},
    groups.length ? h("div", {class: "stack tight"}, groups.slice(0, 8).map((g) => h("div", {class: "an-group"},
      h("p", null, h("b", null, `${fmt.int(g.size)}개 계좌`), h("span", {class: "muted"}, ` · 매매법 ${fmt.int(g.strategies)}개 · 상관 최소 ${fmt.num(g.min_corr, 2)} / 평균 ${fmt.num(g.mean_corr, 2)}`,
        g.same_of_busy_mean != null ? ` · 포지션 있을 때 같은 코인·방향 ${fmt.pct(g.same_of_busy_mean, 0, false)}` : "")),
      h("div", {class: "row wrap an-chips"}, g.accounts.slice(0, 8).map((a) => h("a", {class: "pp", href: env.ctx.href("account", a.account_id || a), title: a.account_id || a}, acctLabel(a.account_id || a))),
        g.accounts.length > 8 ? h("span", {class: "muted"}, `외 ${fmt.int(g.accounts.length - 8)}`) : null),
      g.combined ? h("p", {class: "an-note"}, `모두 같이 돌렸다면: 최대 낙폭 ${fmt.pct(-g.combined.max_dd, 1)} (계좌 평균 ${fmt.pct(-g.combined.avg_member_max_dd, 1)}) · 최악의 날 ${fmt.money(g.combined.worst_day, true)} (각자 최악의 날 합 ${fmt.money(g.combined.members_worst_days_sum, true)})${g.combined.dd_ratio != null && g.combined.dd_ratio > 0.8 ? " · 합쳐도 낙폭이 거의 줄지 않음" : ""}`) : null)),
      groups.length > 8 ? h("p", {class: "muted"}, `외 ${fmt.int(groups.length - 8)}개 묶음`) : null)
      : h("p", {class: "muted"}, ac.strategy_enough_data < 2 ? "아직 기록이 충분한 계좌가 적어 묶음을 만들 수 없습니다." : `상관 ${fmt.num(r.group_corr, 1)} 이상으로 묶인 계좌가 없습니다.`),
    pr && pr.corr && pr.corr.pairs ? h("p", {class: "an-note"}, `비교한 매매법 계좌 쌍 ${fmt.int(pr.corr.pairs)}개: 상관 중앙값 ${fmt.num(pr.corr.median, 2)}, ${fmt.num(r.group_corr, 1)} 이상 ${fmt.pct(pr.corr.share_ge_group, 0, false)}`,
      pr.random_reference && pr.random_reference.random_pairs && pr.random_reference.random_pairs.pairs ? ` · 동전 봇끼리(우연의 기준) 중앙값 ${fmt.num(pr.random_reference.random_pairs.median, 2)}` : "",
      `. 기록 부족으로 뺀 쌍 ${fmt.int(pr.insufficient)}개.`) : null,
    groups.some((g) => g.combined) ? ui.assume() : null));
  if (!ex || !(ex.top || []).length) out.push(ui.card({plate: "한 코인에 몰린 순간"}, h("p", {class: "muted"}, "겹친 포지션 기록이 없습니다.")));
  else {
    const pg = ui.pager({size: 8, row: (m) => h("div", {class: "lrow an-row", role: "listitem"},
      h("span", {class: "rk"}, fmt.kst(m.ts)), h("span", {class: "lname"}, fmt.coin(m.symbol), " ", ui.sideTag(m.side)),
      h("span", {class: "ret num"}, `${fmt.int(m.count)}개`),
      h("span", {class: "meta"}, h("span", null, `매매법 ${fmt.int(m.strategies)}개`), m.minutes != null ? h("span", null, `절반 이상 ${fmt.dur(m.minutes * 60)} 유지`) : null,
        h("span", {class: "an-accts"}, m.accounts.slice(0, 4).map(acctLabel).join(", "), m.accounts.length > 4 ? ` 외 ${fmt.int(m.accounts.length - 4)}` : "")))});
    pg.set(ex.top);
    out.push(ui.card({plate: "한 코인에 몰린 순간", sub: "같은 코인·같은 방향에 들어가 있던 계좌 수 (5분마다)"},
      h("p", null, "가장 많이 몰린 때 ", h("b", null, `${fmt.int(ex.max.count)}개`), ` (${fmt.coin(ex.max.symbol)} ${fmt.sideKo(ex.max.side)}, ${fmt.kst(ex.max.ts)}), 보통은 ${fmt.num(ex.percentiles.p50, 0)}개`,
        ex.share_ge5 != null ? `, 시간의 ${fmt.pct(ex.share_ge5, 0, false)}는 5개 이상` : "", ". 이 계좌들이 한 계정에 있었다면 같이 벌고 같이 잃습니다."),
      pg.el));
  }
  return out;
}

// ---------------------------------------------------------------- 조합 시너지 (/api/analysis/synergy)
export function synergy(d, env) {
  const out = [viewHead({plate: "조합 시너지", q: "매매법 몇 개를 같이 돌렸다면",
    meta: `${fmt.int(d.days || 0)}일 · 기존 36 매매법 · ${d.label || ""}`, at: d.computed_at, stale: d.stale,
    read: "매매법 2~5개를 같은 크기로 같이 돌렸다면의 합친 자금 곡선 중 점수(총손익 ÷ 최대 낙폭)가 높은 순입니다. 분산 효과 = 각자 최대 낙폭의 합 ÷ 합친 곡선의 최대 낙폭 (1이면 위험이 안 나뉨).",
    warn: [thin(d.days || 0, 14, "날 수(하루 손익)"), "수만 개 조합 중 고른 최고값이라 실제보다 좋아 보이기 쉽습니다. 계좌를 묶거나 바꾸지 않습니다: 설명용, 판정 아님."]})];
  const pg = ui.pager({size: 8, empty: "조합이 없습니다", row: (r) => h("div", {class: "lrow an-row", role: "listitem"},
    h("span", {class: "rk"}, `${fmt.int(r.k || r.names.length)}개`), h("span", {class: "lname an-wrap"}, r.names.join(" + ")),
    h("span", {class: ["ret num", fmt.tone(r.return_pct)]}, fmt.pct(r.return_pct)),
    h("span", {class: "meta"}, h("span", null, `최대 낙폭 ${r.max_dd_pct ? fmt.pct(-r.max_dd_pct, 1) : "—"}`), h("span", null, `점수 ${fmt.num(r.score, 2)}`),
      h("span", null, `분산 효과 ${r.combined_never_fell ? "내려간 적 없음" : fmt.num(r.div_ratio, 2)}`), r.same_bet ? ui.pill("같은 베팅 포함", "warn") : null))});
  pg.set(d.top || []);
  const sh = d.shuffled_days;
  out.push(ui.card({plate: "점수 높은 조합", sub: "오른쪽 = 합친 자금 대비 수익"}, pg.el,
    sh ? h("p", {class: "an-note"}, `날짜를 섞은 자료로 같은 탐색을 ${fmt.int(sh.runs)}번 했을 때 최고 점수 중앙값 ${fmt.num(sh.null_best_median, 2)}, 진짜 최고 ${fmt.num(sh.real_best, 2)}: `,
      sh.real_beats_share != null && sh.real_beats_share < 0.9 ? "섞은 자료에서도 이만한 점수가 나옵니다 (특별하다고 보기 어려움)." : "섞은 자료보다 높게 나왔지만, 기간이 짧으면 우연일 수 있습니다.",
      env.ready && sh.rank_p != null ? ` (rank_p ${fmt.num(sh.rank_p, 3)})` : "") : null,
    d.coin_flips ? h("p", {class: "an-note"}, `동전 봇 ${fmt.int(d.coin_flips.units)}개로 같은 탐색: 최고 점수 ${fmt.num(d.coin_flips.best_score, 2)} (조건이 같지 않은 참고 기준)`) : null,
    (d.same_bet_pairs || []).length ? h("p", {class: "an-note"}, "사실상 같은 베팅 쌍: ", d.same_bet_pairs.slice(0, 6).map((p) => (p.strategies || []).join(" · ")).join(" / ")) : null,
    (d.clusters || []).length ? ui.moreText(`하루 손익이 같이 움직이는 묶음 (상관 0.7 이상): ${d.clusters.slice(0, 5).map((g) => g.join(", ")).join(" / ")}`, 2, "an-note") : null,
    ui.refNote(env.verdictTs), ui.assume()));
  return out;
}

// ---------------------------------------------------------------- GH Coin (feature; /api/ghcoin)
const GH_ST = {long: "롱 타점", short: "숏 타점", longWait: "롱 대기", shortWait: "숏 대기", wait: "관망"};
const GH_RES = {win: "익절1", loss: "손절", expire: "24시간 만료", flip: "반대 신호"};
const r2 = (x) => (x == null ? "—" : `${fmt.num(x, 2, true)}R`);
export function ghcoin(d, env) {
  const t = d.total || {};
  const out = [viewHead({plate: "GH Coin", q: "GH Coin 타점은 동전 던지기와 달랐나",
    meta: `${d.alive ? "기록 중" : "멈춤 또는 시작 전"} · 끝난 타점 ${fmt.int(t.calls || 0)}개 · 열린 타점 ${fmt.int(d.open || 0)}개`,
    read: "GH Coin 코드를 고치지 않고 서버에서 따로 돌린 기록입니다. paper 계좌와는 섞이지 않습니다. 손익 단위 R = 손절까지 거리.",
    warn: [thin(t.calls || 0, 30, "끝난 타점")]})];
  if (t.calls) {
    out.push(ui.card({plate: "합계", sub: "참고"},
      h("p", null, Object.entries(t.results || {}).map(([k, n]) => `${GH_RES[k] || k} ${fmt.int(n)}`).join(" · ")),
      h("p", null, "합계 ", h("b", {class: fmt.tone(t.net_r)}, r2(t.net_r)), ` (수수료·미끄러짐 뒤, 그 전 ${r2(t.gross_r)}) · 같은 시각 동전 던지기 ${r2(t.coin_flip_net_r)}`,
        env.ready && t.p_coin_flip != null ? ` · p ${fmt.num(t.p_coin_flip, 4)}` : ""),
      ui.table([{label: "코인", l: true, get: ([s]) => fmt.coin(s)}, {label: "타점", get: ([, s]) => fmt.int(s.calls)},
        {label: "수익 비율", get: ([, s]) => fmt.pct(s.win_rate, 0, false)}, {label: "합계", get: ([, s]) => r2(s.net_r)}, {label: "동전 던지기", get: ([, s]) => r2(s.coin_flip_net_r)}],
      Object.entries(d.by_coin || {}).filter(([, s]) => s.calls)), ui.refNote(env.verdictTs)));
  } else out.push(ui.card({}, h("p", {class: "muted"}, `끝난 타점이 아직 없습니다 (열린 타점 ${fmt.int(d.open || 0)}개).`)));
  const coins = Object.entries((d.board || {}).coins || {});
  if (coins.length) out.push(ui.card({plate: "지금 GH Coin 판단"}, ui.table([
    {label: "코인", l: true, get: ([s]) => fmt.coin(s)}, {label: "판단", l: true, get: ([, c]) => [GH_ST[c.state] || c.state, c.why ? h("span", {class: "muted"}, ` ${c.why}`) : null]},
    ...["5", "15", "60", "240"].map((k) => ({label: {5: "5분", 15: "15분", 60: "1시간", 240: "4시간"}[k], get: ([, c]) => (c.scores && c.scores[k] != null ? fmt.num(c.scores[k] * 100, 0) : "—")})),
  ], coins)));
  return out;
}

// ---------------------------------------------------------------- 45개 질문 (feature; /api/analysis/questions)
const QST = {done: ["답 있음", "good"], partial: ["일부", "accent"], todo: ["아직", "thin"], na: ["해당 없음", ""], checking: ["확인 중", "thin"]};
export function questions(d) {
  const c = d.counts || {};
  const out = [viewHead({plate: "45개 질문", q: `질문 ${fmt.int(d.total || 0)}개 점검표`, meta: [d.source ? `출처 ${d.source}` : null, d.updated].filter(Boolean).join(" · "),
    read: "질문마다 지금 답이 있는지 표시합니다: 답 있음 · 일부 · 아직 · 해당 없음 · 확인 중. 일부 = 기존 36만 답하거나 한쪽만 답함."})];
  out.push(h("div", {class: "stats s4"}, ui.stat("답 있음", fmt.int(c.done || 0)), ui.stat("일부", fmt.int(c.partial || 0)), ui.stat("아직", fmt.int(c.todo || 0)), ui.stat("해당 없음", fmt.int(c.na || 0))));
  if (c.checking) out.push(h("p", {class: "an-note"}, `확인 중 ${fmt.int(c.checking)}개: 코드로 아직 확인하지 못한 질문 (추측해서 표시하지 않음).`));
  const pg = ui.pager({size: 10, row: (q) => h("div", {class: "lrow an-row", role: "listitem"}, h("span", {class: "rk"}, `${q.n}.`),
    h("span", {class: "lname an-wrap"}, q.q), h("span", {class: "ret"}, ui.pill(...(QST[q.status] || QST.todo))),
    h("span", {class: "meta"}, q.group ? h("span", null, q.group) : null, q.where ? h("span", null, `어디서: ${q.where}`) : null, q.note ? h("span", null, q.note) : null))});
  pg.set(d.questions || []);
  out.push(ui.card({plate: "질문"}, pg.el));
  return out;
}

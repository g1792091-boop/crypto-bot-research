// 분석: 코인·장세 지도 / 코인·시간대 / 진입 순간 / 상황 태그 (builder C; old analysis.js rMap / rEntry, breakdown.js,
// strat.js loss patterns across all accounts). Where the trades made and lost money, cut many ways. Descriptive only:
// many cells are looked at, so one odd cell is a hypothesis, never a rule. Coin flips are the 참고 baseline (refNote).
import {h, put, ui, fmt, motion} from "../core/pb.js";
import {viewHead, thin, cell, cmpList, dimSeg, acctLabel} from "./analysis-kit.js";
import {tagRows} from "./strategies-panels.js";

// ---------------------------------------------------------------- 코인·장세 지도 (/api/analysis/map)
const MAP_DIMS = [["by_coin", "코인"], ["by_regime", "진입 때 장세"], ["by_session", "시간대"], ["by_weekday", "평일·주말"], ["by_side", "방향"], ["by_timeframe", "봉"]];
const VOL_KO = {low: "낮음", mid: "보통", high: "높음", unknown: "모름"};
export function map(d, env) {
  const s = d.strategy || {}, f = d.coin_flips || {}, min = d.small_n || 10;
  const out = [viewHead({plate: "코인·장세 지도", q: "어디서 벌고 어디서 잃었나",
    meta: `최근 끝난 거래 최대 ${fmt.int(d.cap)}건 기준 · 기존 36 매매법 ${fmt.int(s.trades || 0)}건 · 동전 봇 ${fmt.int(f.trades || 0)}건`, at: d.computed_at, stale: d.stale,
    read: `한 칸 = 거래 수 · 이긴 비율 · 손익 합계. ${fmt.int(min)}건 미만 칸은 표본 적음(결론 없음). 동전 봇(무작위 진입)은 같은 칸의 비교 기준입니다.`,
    warn: [thin(s.trades || 0, 30, "매매법 계좌 끝난 거래")]})];
  if (!s.trades) { out.push(ui.card({}, ui.empty("아직 끝난 거래가 없습니다."))); return out; }
  const dims = MAP_DIMS.filter(([k]) => Object.keys(s[k] || {}).length || Object.keys(f[k] || {}).length);
  const eb = d.entry_buckets;
  if (eb && eb.volatility) dims.push(["eb_vol", "진입 때 변동성"]);
  if (eb && eb.weekday) dims.push(["eb_wd", "요일"]);
  const body = h("div");
  const seg = dimSeg("map", dims.map(([id, label]) => ({id, label})), dims[0][0], () => paint(true), true);
  function paint(anim) {
    const k = seg.get();
    if (k === "eb_vol" || k === "eb_wd") {
      const src = k === "eb_vol" ? eb.volatility : eb.weekday;
      put(body, h("div", {class: "an-cmp"}, Object.entries(src).map(([b, c]) => h("div", {class: "an-cmprow one"},
        h("b", {class: "an-cmpk"}, k === "eb_vol" ? VOL_KO[b] || b : b),
        h("span", null, c && c.n ? [cell({n: c.n, wr: c.wr}, min), ` · 평균 ROE `, h("b", {class: fmt.tone(c.roe)}, fmt.pct(c.roe))] : "—")))),
        h("p", {class: "an-note"}, k === "eb_vol" ? "같은 코인·봉의 지난 30일과 비교한 진입 때 변동성 ('진입 순간' 계산에서 옴)." : "진입한 요일 (한국 시간)."));
    } else {
      const keys = [...new Set([...Object.keys(s[k] || {}), ...Object.keys(f[k] || {})])];
      put(body, cmpList(keys.map((x) => ({label: k === "by_timeframe" ? fmt.tfKo(x) : x, a: cell((s[k] || {})[x], min), b: cell((f[k] || {})[x], min)}))));
    }
    if (anim) motion.swap(body);
  }
  paint(false);
  out.push(ui.card({plate: "나눠 보기"}, seg.el, body,
    !eb ? h("p", {class: "an-note"}, "'진입 순간'을 한 번 열면 그 계산으로 변동성·요일 칸이 여기에 붙습니다.") : null,
    s.note ? ui.moreText(s.note, 2, "an-note") : null, ui.refNote(env.verdictTs), ui.assume()));
  return out;
}

// ---------------------------------------------------------------- 코인·시간대 (/api/breakdown)
const SES = {asia: "아시아장 09~16시", europe: "유럽장 16~22시", us: "미국장 22~05시", dawn: "새벽 05~09시"};
const WIN = {funding: "펀딩 정산 ±10분", us_open: "미국장 개장 ±1시간", macro: "미국 지표 발표 (08:30 뉴욕) ±30분"};
const WD = {Mon: "월", Tue: "화", Wed: "수", Thu: "목", Fri: "금", Sat: "토", Sun: "일"};
export function sessions(d, env) {
  const min = d.min_n || 30;
  const out = [viewHead({plate: "코인·시간대", q: "어느 코인, 어느 시간에 잘 됐나",
    meta: `기존 36 매매법 계좌의 끝난 거래 ${fmt.int(d.trades)}건 · 칸마다 ${fmt.int(min)}건 미만은 결론 아님`, at: d.computed_at, stale: d.stale,
    read: "진입한 때(한국 시간)로 나눈 성적입니다. 동전 봇 칸은 같은 기준의 우연 기준(참고)입니다.",
    warn: [thin(d.trades, min, "끝난 거래")]})];
  const tabs = [{id: "coin", label: "코인"}];
  if (d.sessions) tabs.push({id: "ses", label: "시간대"}, {id: "win", label: "특별 시간"}, {id: "wd", label: "요일"});
  if (d.volatility) tabs.push({id: "vol", label: "변동성 급등"});
  const body = h("div");
  const seg = dimSeg("bd", tabs, "coin", () => paint(true), true);
  const c2 = (c) => cell(c ? {n: c.n, win_rate: c.win_rate, pnl: c.pnl, status: c.status} : null, min);
  function paint(anim) {
    const k = seg.get();
    if (k === "coin") {
      put(body, cmpList(Object.entries(d.by_coin || {}).map(([sym, c]) => ({label: fmt.coin(sym), a: c2(c.strategies), b: c2(c.coin_flips)})), {label: "코인"}),
        h("div", {class: "an-best"}, h("b", null, "코인마다 잘 된 계좌 (10건 이상)"),
          Object.entries(d.by_coin || {}).some(([, c]) => (c.best || []).length)
            ? Object.entries(d.by_coin || {}).filter(([, c]) => (c.best || []).length).map(([sym, c]) => h("p", null, h("b", null, fmt.coin(sym)), " ",
              c.best.map((b, i) => [i ? " · " : "", h("a", {href: env.ctx.href("account", b.account)}, acctLabel(b.account)), " ", h("span", {class: fmt.tone(b.pnl)}, fmt.money(b.pnl, true))])))
            : h("p", {class: "muted"}, "아직 한 코인에서 10건 넘게 거래한 계좌가 없습니다.")));
    } else if (k === "ses") {
      const p = d.sessions.primary || [];
      const at = (day, ses) => p.find((c) => c.day === day && c.session === ses);
      put(body, cmpList(Object.keys(SES).map((s0) => ({label: SES[s0], a: c2(at("weekday", s0)), b: c2(at("weekend", s0))})), {label: "시간대", a: "평일", b: "주말"}));
    } else if (k === "win") {
      put(body, cmpList((d.sessions.windows || []).map((w) => ({label: WIN[w.window] || w.window, a: c2(w.inside), b: c2(w.outside)})), {label: "특별 시간", a: "그 시간에 진입", b: "그 밖"}));
    } else if (k === "wd") {
      put(body, h("div", {class: "an-cmp"}, (d.sessions.weekday || []).map((c) => h("div", {class: "an-cmprow one"}, h("b", {class: "an-cmpk"}, WD[c.weekday] || c.weekday), h("span", null, c2(c))))));
    } else {
      const v = d.volatility;
      put(body, cmpList([{label: "변동성", a: c2(v.spike), b: c2(v.normal)}], {label: "", a: "급등 때 진입", b: "평소"}),
        h("p", {class: "an-note"}, `판단 못 함 ${fmt.int(v.unknown)}건 (최근 30일 신호 50개 이상 필요). 급등 = 진입 때 ATR/가격이 같은 코인·봉 지난 30일 신호의 상위 10%.`));
    }
    if (anim) motion.swap(body);
  }
  paint(false);
  out.push(ui.card({plate: "나눠 보기"}, seg.el, body,
    h("p", {class: "an-note"}, "설명용 표입니다. 이 표로 계좌 규칙을 바꾸지 않습니다. 패턴이 보이면 에이전트가 5년치로 시험하고, 통과하면 새 계좌로 비교합니다."),
    ui.refNote(env.verdictTs), ui.assume()));
  return out;
}

// ---------------------------------------------------------------- 진입 순간 (/api/analysis/entry)
const DIM_KO = {strength: "진입 강도", volatility: "변동성", body: "몸통 크기(ATR 대비)", wick_against: "반대쪽 꼬리", wick_with: "같은 쪽 꼬리",
  close_loc: "종가 위치", streak: "연속 봉", pattern: "봉 모양", liq: "직전 강제청산 몰림", hold: "보유 시간", funding: "펀딩비", weekday: "요일"};
const BK_KO = {weak: "약함", mid: "중간", strong: "강함", unknown: "모름", low: "낮음", high: "높음", with_1: "같은 방향 1개", with_2: "같은 방향 2개",
  "with_3+": "같은 방향 3개+", against_1: "반대 1개", "against_2+": "반대 2개+", doji: "도지", engulf_with: "장악형(같은 방향)",
  engulf_against: "장악형(반대)", pin_with: "망치형(같은 방향)", pin_against: "망치형(반대)", none: "없음", burst_with: "몰림(같은 방향)",
  burst_against: "몰림(반대)", neg: "마이너스", base: "기본", "<30m": "30분 미만", "30m-2h": "30분~2시간", "2h-8h": "2~8시간", "8h+": "8시간+"};
export function entry(d, env) {
  const cov = d.coverage || {}, mc = d.multiple_comparisons || {}, min = d.min_n || 10;
  const T = cov.trades || d.trades || 1;
  const out = [viewHead({plate: "진입 순간", q: "들어가는 순간의 모습에 따라 성적이 달랐나",
    meta: `기존 36 매매법의 끝난 거래 ${fmt.int(d.trades || 0)}건 · 칸 최소 ${fmt.int(min)}건`, at: d.computed_at || d.generated_ms, stale: d.stale,
    read: "진입 봉의 모양·변동성·보유 시간 같은 것으로 거래를 나눴습니다. 칸을 아주 많이 보므로 20칸 중 1칸쯤은 우연만으로도 달라 보입니다: 칸 차이는 가설일 뿐입니다.",
    warn: [thin(d.trades || 0, 100, "끝난 매매법 거래"), mc.note || null]})];
  if (!d.trades) { out.push(ui.card({}, ui.empty(d.note || "아직 끝난 거래가 없습니다"))); return out; }
  const dims = (d.dims || Object.keys(d.all || {})).filter((k) => Object.keys((d.all || {})[k] || {}).length);
  const body = h("div");
  const seg = dimSeg("entry", dims.map((k) => ({id: k, label: DIM_KO[k] || k})), dims[0], () => paint(true), true);
  function paint(anim) {
    const k = seg.get(), t = (d.all || {})[k] || {}, order = (d.bucket_order || {})[k] || Object.keys(t);
    const keys = [...order.filter((b) => t[b]), ...Object.keys(t).filter((b) => !order.includes(b))];
    put(body, ui.table([
      {label: "칸", l: true, get: (b) => h("span", {class: t[b].n < min ? "muted" : ""}, BK_KO[b] || b)},
      {label: "거래", get: (b) => fmt.int(t[b].n)},
      {label: "승률", get: (b) => fmt.pct(t[b].wr, 0, false)},
      {label: "평균 ROE", get: (b) => h("span", {class: fmt.tone(t[b].roe)}, fmt.pct(t[b].roe))},
      {label: "", get: (b) => ui.smallSample(t[b].n, min)},
    ], keys));
    if (anim) motion.swap(body);
  }
  paint(false);
  out.push(ui.card({plate: "모습별 성적"}, seg.el, body,
    h("p", {class: "an-note"}, `자료가 붙은 비율: 봉 모양 ${fmt.pct((cov.candle || 0) / T, 0, false)} · 변동성 ${fmt.pct((cov.volatility || 0) / T, 0, false)} · 진입 강도 ${fmt.pct((cov.strength || 0) / T, 0, false)} · 강제청산 ${fmt.pct((cov.liq || 0) / T, 0, false)}${cov.liq_note ? ` (${cov.liq_note})` : ""}`)));
  if ((d.notable || []).length) {
    const pg = ui.pager({size: 8, row: (x) => h("a", {class: "lrow click an-row", role: "listitem", href: env.ctx.href("strategies", x.strategy)},
      h("span", {class: "rk"}, String(x.strategy).split("_")[0]), h("span", {class: "lname"}, x.name_ko || x.strategy),
      h("span", {class: ["ret num", fmt.tone(x.roe)]}, fmt.pct(x.roe)),
      h("span", {class: "meta"}, h("span", null, `${DIM_KO[x.dim] || x.dim}: ${BK_KO[x.bucket] || x.bucket}`), h("span", null, `${fmt.int(x.n)}건`),
        h("span", null, `매매법 평균 ${fmt.pct(x.strategy_roe)} (${fmt.int(x.strategy_n)}건)`), ui.smallSample(x.n, min)))});
    pg.set(d.notable);
    out.push(ui.card({plate: "평소와 가장 달랐던 칸", sub: "매매법마다 하나 · 가설일 뿐"}, pg.el));
  }
  const sk = d.skipped_signals;
  if (sk) {
    const so = sk.skipped_outcome || {};
    const nt = Object.entries(sk.not_taken || {}).filter(([, v]) => typeof v === "number");
    out.push(ui.card({plate: "들어가지 않은 신호"},
      h("p", null, nt.length ? nt.map(([k, v]) => `${k} ${fmt.int(v)}`).join(" · ") : "들어가지 않은 신호 기록이 없습니다."),
      so.signals ? h("p", null, `건너뛴 신호 ${fmt.int(so.signals)}개 중 결과가 나온 ${fmt.int(so.resolved)}개: 승률 ${fmt.pct(so.wr, 0, false)} · 평균 ROE `,
        h("b", {class: fmt.tone(so.roe)}, fmt.pct(so.roe)), so.entered_roe != null ? ` (들어간 거래 평균 ${fmt.pct(so.entered_roe)})` : "", " ", ui.smallSample(so.resolved, min)) : null,
      sk.note ? ui.moreText(sk.note, 2, "an-note") : null));
  }
  if (d.note) out.push(h("p", {class: "an-note an-foot"}, d.note));
  return out;
}

// ---------------------------------------------------------------- 상황 태그 (/api/cards/stats, every account)
export function tags(d) {
  return [viewHead({plate: "상황 태그", q: "손실에 자주 붙은 상황은?",
    meta: `최근 30일 끝난 거래 ${fmt.int(d.trades || 0)}건 (최근 2,000건까지, 동전 봇 포함 모든 계좌)`,
    read: "손실이 날 때마다 코드가 거래에 상황 표시(태그)를 붙입니다. 경제지표 발표 전후, 추세 반대 진입, 수익 났다가 손절 같은 것입니다. 손실 쪽 막대가 이익 쪽보다 훨씬 길면 먼저 볼 곳입니다.",
    warn: [thin(d.trades || 0, 30, "끝난 거래")]}),
  ui.card({plate: "태그별 손실 · 이익 비율"}, ...tagRows(d),
    h("p", {class: "an-note"}, "설명용 표시이며 매매 규칙이 아닙니다. 매매법 하나의 태그는 매매법 화면의 '손실 패턴'에 있습니다."))];
}

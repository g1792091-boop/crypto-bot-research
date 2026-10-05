// 분석: 손익비·위험 / 실전 준비도 / 충격 테스트 (builder C; old analysis.js rRisk / rReady / rShock).
// All of these stand on the 36 strategy accounts (kind 'strategy'), with the coin flips as the 참고 baseline.
// HONESTY: the readiness marks are neutral words (충족 / 아님 / 판단 전), never green ✓ / red ✕; money has assume().
import {h, put, ui, fmt} from "../core/pb.js";
import {viewHead, thin, pp, acctLabel, shareBar, dimSeg} from "./analysis-kit.js";

const EXIT_KO = {LOCK: "익절 잠금", SL: "손절", LIQ: "강제청산", other: "기타 (시간·정지 등)"};

// ---------------------------------------------------------------- 손익비·위험
export function risk(d, env) {
  const a = d.all || {}, f = d.coin_flips || {}, dd = d.drawdown || {}, g = a.giveback || {}, r = d.rules || {};
  const out = [viewHead({plate: "손익비·위험", q: "이길 때 얼마, 질 때 얼마? 그리고 얼마나 깊이 빠졌나",
    meta: `기존 36 매매법 계좌의 끝난 거래 ${fmt.int(d.trades)}건 · 동전 봇 ${fmt.int(d.flip_trades)}건`, at: d.computed_at, stale: d.stale,
    read: "손익비 = 평균 이익 ÷ 평균 손실. 본전 승률 = 그 손익비에서 본전이 되는 승률. 차이가 플러스면 실제 승률이 본전 승률보다 높아 남는 쪽입니다.",
    warn: [thin(d.trades, 30, "매매법 계좌 끝난 거래")]})];
  // metrics down, the two groups across: three narrow columns read well on a phone
  const M = [["거래", (x) => fmt.int(x.trades)], ["승률", (x) => fmt.pct(x.win_rate, 0, false)], ["손익비", (x) => fmt.num(x.payoff, 2)],
    ["본전 승률", (x) => fmt.pct(x.breakeven_win_rate, 0, false)], ["차이 (승률 − 본전)", (x) => h("span", {class: fmt.tone(x.gap_pp)}, pp(x.gap_pp))],
    ["거래당 자금 대비", (x) => h("span", {class: fmt.tone(x.expectancy_eq)}, fmt.pct(x.expectancy_eq, 2))]];
  const have = (x) => x && x.trades;
  out.push(ui.card({plate: "매매법 vs 동전 봇", sub: "참고"},
    ui.table([{label: "", l: true, get: (m) => m[0]},
      {label: "매매법 계좌", get: (m) => (have(a) ? m[1](a) : "—")},
      {label: "동전 봇", get: (m) => (have(f) ? m[1](f) : "—")}], M),
    h("p", {class: "an-note"}, "동전 봇 = 같은 청산 규칙으로 무작위로 들어가는 비교 계좌.",
      (a.trades || 0) < 30 || (f.trades || 0) < 30 ? [" ", ui.pill("표본 적음", "thin"), ` 30건 미만인 쪽이 있습니다 (매매법 ${fmt.int(a.trades || 0)}건 · 동전 봇 ${fmt.int(f.trades || 0)}건).`] : null),
    h("p", {class: "an-note"}, `지금 규칙: 손절 ${fmt.num(r.stop_atr, 1)} ATR · 레버리지 ${r.leverage || "—"} · 최고 수익 ${fmt.pct(r.first_trigger, 0)}에서 ${fmt.pct(r.first_lock, 0)} 잠금. 이 규칙은 손익비가 낮고 본전 승률이 높게 나오는 것이 설계상 자연스럽습니다.`),
    ui.refNote(env.verdictTs)));
  // how winners gave back and how trades ended
  const ex = a.exit_share || {};
  out.push(ui.card({plate: "어떻게 끝났나", sub: "매매법 계좌"},
    h("div", {class: "an-bars"}, Object.keys(EXIT_KO).filter((k) => ex[k] != null).map((k) => h("div", {class: "an-barrow"},
      h("span", null, EXIT_KO[k]), shareBar(ex[k], k === "LOCK" ? "up" : k === "other" ? "acc" : "down"), h("b", {class: "num"}, fmt.pct(ex[k], 1, false))))),
    g.winners ? h("p", null, `이긴 거래 ${fmt.int(g.winners)}건: 거래 중 최고 수익(ROE) 평균 `, h("b", {class: "up"}, fmt.pct(g.mean_best_roe)), " → 실제 ",
      h("b", {class: "up"}, fmt.pct(g.mean_roe)), ` (최고점의 ${fmt.pct(g.kept_share, 0, false)}를 지키고 나머지는 돌려줌).`) : null,
    a.losers_reached_first_lock != null ? h("p", {class: "an-note"}, `진 거래 중 첫 잠금 발동선까지 갔다가 진 것 ${fmt.int(a.losers_reached_first_lock)}건.`) : null));
  // drawdown and bust probability per timeframe
  const tfRows = Object.entries(dd.timeframes || {}).map(([tf, x]) => ({label: fmt.tfKo(tf), x}));
  if (dd.coin_flips) tfRows.push({label: "동전 봇", x: dd.coin_flips});
  out.push(ui.card({plate: "낙폭·파산 위험"},
    h("p", {class: "an-note"}, `봉별 = 그 봉의 매매법 계좌를 합친 자금. 파산 확률 = 계좌마다 지금까지 끝난 거래를 다시 뽑아 앞으로 ${fmt.int(dd.horizon_days || 30)}일을 ${fmt.int(dd.paths || 10000)}번 흉내 냈을 때 파산선 아래로 간 비율 (거래 ${fmt.int(dd.min_trades || 20)}건 이상 계좌만, 가장 높은 계좌). 예측이 아니라 설명용입니다.`),
    h("div", {class: "stats s4"}, ui.stat("흉내 낸 계좌", fmt.int(dd.simulated), `거래 적어 못 함 ${fmt.int(dd.too_few)}`),
      ui.stat("파산 확률 5% 이상", fmt.int(dd.p_bust_over_5pct), "계좌 수"), ui.stat("−50% 확률 10% 이상", fmt.int(dd.p_dd50_over_10pct), "계좌 수"),
      ui.stat("이미 파산", fmt.int((dd.busted || []).length), "계좌 수")),
    !dd.simulated ? h("p", {class: "an-warn"}, "아직 거래 20건이 넘은 계좌가 없어 파산 확률을 계산하지 않았습니다.") : null,
    tfRows.length ? ui.table([
      {label: "봉", l: true, get: (r0) => r0.label},
      {label: "거래", get: (r0) => fmt.int(r0.x.trades)},
      {label: "지금 낙폭", get: (r0) => fmt.pct(-(r0.x.dd_now_pct || 0), 1)},
      {label: "최대 낙폭", get: (r0) => (r0.x.max_dd_pct ? fmt.pct(-r0.x.max_dd_pct, 1) : "—")},
      {label: "최악의 날", get: (r0) => (r0.x.worst_day ? h("span", {class: fmt.tone(r0.x.worst_day.pnl)}, fmt.money(r0.x.worst_day.pnl, true)) : "—")},
      {label: "파산 확률 (최고)", get: (r0) => (r0.x.p_bust_max ? fmt.pct(r0.x.p_bust_max.p, 1, false) : "—")},
      {label: "파산 계좌", get: (r0) => fmt.int(r0.x.busted || 0)},
    ], tfRows) : null,
    ui.assume()));
  // per strategy (36): a paged list, tap → 매매법
  const pg = ui.pager({size: 10, row: (s) => h("a", {class: "lrow click an-row", role: "listitem", href: env.ctx.href("strategies", s.strategy)},
    h("span", {class: "rk"}, String(s.strategy).split("_")[0]), h("span", {class: "lname"}, s.name_ko || s.strategy),
    h("span", {class: ["ret num", fmt.tone(s.gap_pp)], title: "실제 승률 − 본전 승률"}, pp(s.gap_pp)),
    h("span", {class: "meta"}, h("span", null, `거래 ${fmt.int(s.trades)}`), h("span", null, `승률 ${fmt.pct(s.win_rate, 0, false)}`),
      h("span", null, `손익비 ${fmt.num(s.payoff, 2)}`), h("span", null, `본전 ${fmt.pct(s.breakeven_win_rate, 0, false)}`),
      s.max_dd_pct ? h("span", null, `최대 낙폭 ${fmt.pct(-s.max_dd_pct, 1)}`) : null,
      s.p_bust_max ? h("span", null, `파산 확률 ${fmt.pct(s.p_bust_max.p, 1, false)}`) : null,
      ui.smallSample(s.trades, d.small_n || 10), s.busted ? ui.pill(`파산 ${fmt.int(s.busted)}`, "bad") : null))});
  pg.set(d.strategies || []);
  out.push(ui.card({plate: "매매법별", sub: "봉 계좌 합계 · 오른쪽 숫자 = 승률 − 본전 승률"}, pg.el,
    h("p", {class: "an-note"}, `거래 ${fmt.int(d.small_n || 10)}건 미만은 표본 적음: 우연일 수 있습니다. ${d.label || ""}`)));
  return out;
}

// ---------------------------------------------------------------- 실전 준비도
const MARK = {"✅": ["met", "충족"], "❌": ["no", "아님"], "?": ["wait", "판단 전"]};
export function ready(d, env) {
  const s = d.summary || {}, conds = d.conditions || [], bc = s.by_condition || {};
  const out = [viewHead({plate: "실전 준비도", q: s.headline || "실거래 조건",
    meta: `기존 36 매매법 계좌 ${fmt.int(s.accounts)}개 · ${s.days_running != null ? fmt.num(s.days_running, 1) + "일째" : "—"}${d.label ? " · " + d.label : ""}`, at: d.computed_at, stale: d.stale,
    read: "실거래 전에 미리 정한 조건 8개를 계좌마다 확인합니다. 충족 = 맞음, 아님 = 아직 아님, 판단 전 = 판정이나 기록이 있어야 알 수 있음.",
    warn: [h("p", {class: "an-warn"}, "표시만 합니다: 이 표는 아무것도 켜거나 바꾸지 않고, 실거래는 두 분이 정합니다. 30일 판정 전에는 대부분 '판단 전'입니다."),
      s.q6_6 ? h("p", {class: "an-read"}, h("b", null, s.q6_6)) : null]})];
  out.push(ui.card({plate: "조건 8개", sub: "문서 그대로"},
    h("div", {class: "an-conds", role: "list"}, conds.map((c, i) => {
      const v = bc[c.id] || {};
      return h("div", {class: "an-cond", role: "listitem"}, h("span", {class: "rk"}, String(i + 1)),
        h("div", null, h("b", null, c.label), h("p", {class: "an-note"}, `"${c.quote}" · ${c.doc}${c.line ? ":" + c.line : ""}`)),
        h("div", {class: "an-condn"}, h("span", null, `충족 ${fmt.int(v["✅"] || 0)}`), h("span", null, `아님 ${fmt.int(v["❌"] || 0)}`),
          h("span", null, `판단 전 ${fmt.int(v["아직 판단 불가"] || 0)}`)));
    }))));
  const order = d.order || conds.map((c) => c.id);
  const marks = (r) => h("span", {class: "an-marks", "aria-label": "조건 표시"}, order.map((k, i) => {
    const st = (r.conditions || {})[k] || {}, m = MARK[st.status === "아직 판단 불가" ? "?" : st.status] || MARK["?"];
    const lab = (conds[i] || {}).label || k;
    return h("i", {class: m[0], title: `${i + 1}. ${lab}: ${m[1]}${st.why ? " · " + st.why : ""}`});
  }));
  const pg = ui.pager({size: 10, row: (r) => h("a", {class: "lrow click an-row", role: "listitem", href: env.ctx.href("account", r.account), title: r.account},
    h("span", {class: "rk"}, fmt.tfKo(r.timeframe)), h("span", {class: "lname"}, r.name_ko || acctLabel(r.account)),
    h("span", {class: "ret num"}, `${fmt.int(r.met)}/${fmt.int(r.of)}`),
    h("span", {class: "meta"}, marks(r), h("span", null, `거래 ${fmt.int(r.trades)}`), ui.smallSample(r.trades, 30),
      h("span", {class: fmt.tone(r.pnl)}, fmt.money(r.pnl, true)), r.bust ? ui.pill("파산", "bad") : null))});
  pg.set(d.accounts || []);
  out.push(ui.card({plate: "조건에 가장 가까운 계좌", sub: `오른쪽 = 충족 수${d.accounts_total > (d.accounts || []).length ? ` · 위 ${fmt.int((d.accounts || []).length)}개 / ${fmt.int(d.accounts_total)}개` : ""}`},
    h("p", {class: "an-legend"}, h("span", null, h("i", {class: "met"}), " 충족"), h("span", null, h("i", {class: "no"}), " 아님"), h("span", null, h("i", {class: "wait"}), " 판단 전"),
      h("span", {class: "muted"}, "· 칸을 누르고 있으면 이유")),
    pg.el, ui.assume(null, "손익은 닫힌 거래 기준")));
  return out;
}

// ---------------------------------------------------------------- 충격 테스트
export function shock(d, env) {
  const shocks = d.shocks || [];
  const out = [viewHead({plate: "충격 테스트", q: "가격이 한 번에 크게 움직이면 지금 포지션은?",
    meta: `지금 열린 포지션 ${fmt.int(d.open_positions)}개 (기존 36) · 매매법 계좌 평가 자금 합 ${fmt.money(d.equity_total)}`, at: d.computed_at, stale: d.stale,
    read: "가격이 사이 가격 없이 한 번에 움직였다고 보고 엔진 규칙을 그대로 적용합니다: 청산가를 지나면 증거금 전부, 손절선을 지나면 손절가가 아니라 충격 뒤 가격에 체결(수수료·슬리피지 포함).",
    warn: [!d.open_positions ? "지금 열린 포지션이 없어 충격을 받을 것이 없습니다 (모든 칸이 0)."
      : d.open_positions < 10 ? `열린 포지션이 ${fmt.int(d.open_positions)}개뿐이라 숫자가 작고, 포지션이 바뀌면 크게 달라집니다.` : null]})];
  const body = h("div", {class: "stack tight"});
  const by = {};
  for (const r of d.rows || []) (by[r.coin] ||= {})[r.shock] = r;
  const coins = Object.keys(by).sort((p, q) => (p === "ALL" ? -1 : q === "ALL" ? 1 : p.localeCompare(q)));
  const seg = dimSeg("shock", shocks.map((x) => ({id: String(x), label: fmt.pct(x, 0)})), String(shocks.includes(-0.1) ? -0.1 : shocks[0]), () => paint());
  function paint() {
    const k = Number(seg.get());
    const rows = coins.map((c) => ({c, r: by[c][k]})).filter((x) => x.r);
    put(body, ...(rows.length ? [ui.table([
      {label: "코인 (포지션)", l: true, get: (x) => h("span", null, h("b", null, x.c === "ALL" ? "전체 같이" : x.c), h("span", {class: "muted"}, ` ${fmt.int(x.r.positions)}개`))},
      {label: "자금 변화", get: (x) => h("b", {class: fmt.tone(x.r.change_usd)}, fmt.money(x.r.change_usd, true))},
      {label: "전체 대비", get: (x) => fmt.pct(x.r.share_of_equity, 2)},
      {label: "강제청산", get: (x) => fmt.int(x.r.liquidated)},
      {label: "손절·잠금", get: (x) => fmt.int(x.r.stopped)},
      {label: "파산", get: (x) => h("span", {class: x.r.busted ? "down" : ""}, fmt.int(x.r.busted))},
    ], rows)] : [ui.empty("이 충격에 해당하는 포지션이 없습니다")]));
  }
  paint();
  const ex = Object.entries(d.exposure || {});
  out.push(ui.card({plate: "충격 크기 고르기", sub: "전체 같이 = 모든 코인이 같은 만큼"}, seg.el, body,
    ex.length ? h("p", {class: "an-note"}, "지금 노출: ", ex.map(([c, e]) => `${c} 롱 ${fmt.int(e.long)}·숏 ${fmt.int(e.short)} (증거금 ${fmt.money(e.margin)})`).join(" · ")) : null,
    h("p", {class: "an-note"}, "실제 급변은 여러 번에 나눠 움직여 다를 수 있습니다. 설명용, 판정 아님."),
    ui.assume(null, "가정한 가격 충격으로 계산한 평가 자금 변화")));
  return out;
}

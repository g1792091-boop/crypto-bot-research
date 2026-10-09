// #/home 요약 (round 5: was 홈): the verdict headline ("실전 금지" until something passes; candidates and confirmations first), the goal
// line to 12/31 (CONTRACT 8.7: the line, the five stages, the line closest to "우리 기준" and what it still misses),
// live days and totals, the market now (8.5) with the measured entry cost (8.3), the best / worst account lines, mean
// P&L by account kind and leverage, the ranking leaders against the luck line, recent switches and recent trades
// (each opens its trade chart). home.json + judge.json, every 60 s (drawn again only when the engine wrote a new one).
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {LEVS, KIND_KO, shortOf, tfKo, WINDOW_KO, reasonKo, sideKo, STRAT_KO} from "../labels.js";

const STAGES_KO = ["설치", "데모 진행", "우리 기준 통과", "확인 기간", "실전 후보"];

export async function mount(el, ctx) {
  ctx.setTitle("요약");
  const verdict = h("section", {class: "card hero dl-verdict", "aria-label": "판정"});
  const goal = h("section", {class: "card dl-goal", "aria-label": "12/31 목표"});
  const stats = h("div", {class: "stats dl-s6"});
  const market = h("div");
  const best = h("div"), worst = h("div"), kinds = h("div"), leaders = h("div"), switches = h("div"), trades = h("div");
  el.append(
    ui.screenHead("요약", "데모 랩 한눈에 보기"),
    verdict, goal, stats,
    ui.card({plate: "지금 시장", sub: "코인마다 추세와 변동 · 실제 진입 비용",
      acts: h("a", {class: "btn-line", href: "#/regime"}, "시장 국면")}, market),
    h("div", {class: "grid2"},
      ui.card({plate: "잘 되는 줄", sub: "계좌 × 배수 손익 상위 5"}, best),
      ui.card({plate: "안 되는 줄", sub: "계좌 × 배수 손익 하위 5"}, worst)),
    ui.card({plate: "종류별 평균 손익", sub: "배수마다 계좌 평균 (시작 $1,000 대비)"}, kinds),
    ui.card({plate: "설정 순위 1등", sub: "매매법 × 봉마다 주변 평균 1등과 운 기준선",
      acts: h("a", {class: "btn-line", href: "#/rank"}, "설정 순위 보기")}, leaders),
    h("div", {class: "grid2"},
      ui.card({plate: "최근 교체", sub: "자동 교체·친구 규칙 계좌가 바꾼 설정"}, switches),
      ui.card({plate: "최근 거래", sub: "모든 계좌", acts: h("a", {class: "btn-line", href: "#/trades"}, "거래 기록")}, trades)),
    ui.note("모의 계좌입니다. 바이낸스 실제 시세로 계산하고 수수료·슬리피지·펀딩을 뺍니다. 주문은 넣지 않습니다."));

  let seen = null;
  async function load() {
    let home, judge;
    try {
      [home, judge] = await Promise.all([ctx.api("/api/home"), ctx.api("/api/judge")]);
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!seen) put(verdict, ui.errorBox(e, load));
      return;
    }
    const key = `${home && home.generated_ms}|${judge && judge.generated_ms}`;
    if (key === seen) return;
    seen = key;
    paintVerdict(home, judge);
    if (isMissing(home)) {
      put(stats, ui.missing("요약 자료"));
      put(goal, h("div", {class: "card-h"}, ui.plate("12/31 목표")), ui.none("준비 중"));
      for (const box of [market, best, worst, kinds, leaders, switches, trades]) put(box, ui.empty("준비 중"));
      return;
    }
    paintGoal(home.goal);
    paintMarket(home.regime_now, home.costs_now);
    paintStats(home);
    put(best, lineList(home.best, ctx));
    put(worst, lineList(home.worst, ctx));
    put(kinds, kindTable(home.by_kind));
    put(leaders, leaderTable(home.leaders, ctx));
    put(switches, switchList(home.recent_switches));
    put(trades, tradeList(home.recent_trades, ctx));
  }

  function paintVerdict(home, judge) {
    const t = home && !isMissing(home) && home.totals ? home.totals : {};
    const passed = Number(t.passed || 0), cands = Number(t.candidates || 0), conf = Number(t.confirming || 0);
    const text = judge && !isMissing(judge) && judge.verdict_ko ? judge.verdict_ko : "판정 자료 준비 중";
    const big = cands > 0
      ? h("p", {class: "dl-vbig ok"}, `실전 후보 ${fmt.int(cands)}줄`)
      : conf > 0 ? h("p", {class: "dl-vbig warn"}, `확인 기간 ${fmt.int(conf)}줄`)
        : passed > 0 ? h("p", {class: "dl-vbig ok"}, `통과 ${fmt.int(passed)}줄`)
          : h("p", {class: "dl-vbig no"}, "실전 금지");
    put(verdict,
      h("div", {class: "card-h"}, ui.plate("판정"), h("span", {class: "sub"}, "두 가지 기준으로 매일 확인")),
      big,
      h("p", {class: "dl-vline"}, text),
      h("p", {class: "note"}, cands > 0
        ? "실전 후보는 통과 뒤 4주 확인 기간까지 넘은 줄입니다. 그래도 실제 돈은 두 분이 정하기 전까지 쓰지 않습니다."
        : conf > 0 ? "기준을 넘은 줄이 4주 확인 기간을 지나는 중입니다. 운으로 넘었을 수 있어서, 끝날 때까지 실전에 쓰지 않습니다."
          : passed > 0 ? "통과한 줄이 있어도 실전은 두 분이 정합니다. 판정 화면에서 무엇이 통과했는지 보세요."
            : "아직 어떤 계좌·배수도 기준을 넘지 못했습니다. 넘기 전까지는 실전에 쓰지 않습니다."),
      h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: "#/judge"}, "판정 자세히"),
        h("a", {class: "btn-line", href: "#/howto"}, "기준이 뭔가요?")));
  }

  function paintStats(home) {
    const t = home.totals || {};
    const opt = (v) => (v == null ? "준비 중" : fmt.int(v));
    put(stats,
      ui.stat("실시간", home.live_days != null ? `${fmt.num(home.live_days, 1)}일` : "—", home.phase === "warm" ? "과거 채우는 중" : `계좌 ${fmt.int(t.accounts)}개 · 배수 4줄씩`),
      ui.stat("열린 포지션", fmt.int(t.open_positions), "모든 줄 합계"),
      ui.stat("닫힌 거래", fmt.int(t.trades), "모든 줄 합계"),
      ui.stat("우리 기준 통과", fmt.int(t.passed), "지금 넘은 줄", Number(t.passed) > 0 ? "dl-good" : null),
      ui.stat("확인 기간", opt(t.confirming), "4주 확인 중인 줄"),
      ui.stat("실전 후보", opt(t.candidates), "확인 기간까지 넘은 줄", Number(t.candidates) > 0 ? "dl-good" : null));
  }

  function paintGoal(g) {
    if (!g) { put(goal, h("div", {class: "card-h"}, ui.plate("12/31 목표")), ui.none("준비 중")); return; }
    const stages = Array.isArray(g.stages_ko) && g.stages_ko.length ? g.stages_ko : STAGES_KO;
    const at = Number.isInteger(Number(g.stage)) ? Number(g.stage) : -1;
    const c = g.closest;
    put(goal,
      h("div", {class: "card-h"}, ui.plate("12/31 목표"),
        h("span", {class: "sub"}, g.deadline_ms ? `${fmt.date(g.deadline_ms - 1)}까지` : ""),
        g.days_left != null ? h("span", {class: "acts"}, h("b", {class: "dl-dleft"}, `${fmt.int(g.days_left)}일 남음`)) : null),
      h("p", {class: "dl-goalline"}, g.line_ko || "—"),
      h("ol", {class: "steps dl-steps", "aria-label": "단계"}, stages.map((x, i) => h("li", {class: i < at ? "done" : i === at ? "now" : "",
        "aria-current": i === at ? "step" : null}, `${i + 1}. ${x}`))),
      c ? h("div", {class: "dl-closest"},
        h("div", {class: "dl-evt"}, h("span", {class: "muted"}, "가장 가까운 줄"),
          h("a", {href: ctx.href("account", c.id)}, `${c.name || c.id} ${fmt.lev(c.L)}`),
          ui.pill(`${fmt.int(c.of)}개 중 ${fmt.int(c.ok)}개 통과`, Number(c.ok) >= Number(c.of) ? "good" : "thin")),
        ui.progress(Number(c.of) ? Number(c.ok) / Number(c.of) : 0, null),
        (c.missing_ko || []).length ? h("ul", {class: "dl-ul"}, c.missing_ko.map((x) => h("li", null, h("span", {class: "down"}, "✗ "), x)))
          : h("p", {class: "note"}, "모든 항목을 넘었습니다.")) : null);
  }

  function paintMarket(rows, costs) {
    const list = Array.isArray(rows) ? rows : [];
    const cost = costs && costs.median_entry_bps != null
      ? h("p", {class: "dl-vline"}, `실제 진입 비용 중간값 ${fmt.num(costs.median_entry_bps, 2)}bp `,
        h("span", {class: "muted"}, `(봇의 가정 ${fmt.num(costs.assumed_bps ?? 2, 0)}bp · `),
        h("a", {href: "#/costs"}, "실제 비용"), h("span", {class: "muted"}, ")"))
      : h("p", {class: "note"}, "실제 진입 비용: 기록 없음");
    put(market, list.length ? h("div", {class: "dl-mkt"}, list.map((r) => h("div", {class: "dl-mktc"},
      h("b", null, fmt.coin(r.coin)), ui.regimeChips(r.trend, r.vol)))) : ui.none("준비 중"), cost);
  }

  await load();
  ctx.every(60000, load);
}

function lineList(rows, ctx) {
  if (!rows || !rows.length) return ui.empty("아직 없습니다");
  return h("div", {class: "dl-list"}, rows.map((r, i) => h("a", {class: "lrow click", href: ctx.href("account", r.id)},
    h("span", {class: "rk"}, String(i + 1)),
    h("span", {class: "lname"}, r.name || r.id),
    ui.signed(fmt.pct(r.pnl_pct, true), fmt.tone(r.pnl_pct, fmt.pct(r.pnl_pct)), "span"),
    h("span", {class: "meta"}, fmt.lev(r.L)))));
}

function kindTable(rows) {
  if (!rows || !rows.length) return ui.empty("아직 없습니다");
  return ui.table([
    {label: "종류", l: true, get: (r) => h("span", {class: "dl-kn"}, h("b", null, KIND_KO[r.kind] || r.kind_ko || r.kind), r.accounts ? h("small", {class: "muted"}, `${r.accounts}개`) : null)},
    ...LEVS.map((L) => ({label: `${L}배`, get: (r) => {
      const v = r.mean_pnl_pct ? r.mean_pnl_pct[String(L)] : null;
      return ui.signed(fmt.pct(v, true), fmt.tone(v, fmt.pct(v)));
    }})),
  ], rows, {cls: "dl-kinds"});
}

function leaderTable(rows, ctx) {
  if (!rows || !rows.length) return ui.empty("설정 순위 준비 중");
  return h("div", {class: "stack tight"},
    ui.table([
      {label: "매매법", l: true, get: (r) => h("span", {title: STRAT_KO[shortOf(r.strategy)]}, h("b", null, shortOf(r.strategy)), ` · ${tfKo(r.tf)}`)},
      {label: "1등 설정", l: true, get: (r) => h("span", {class: "mono"}, r.label || "—")},
      {label: "기간", get: (r) => WINDOW_KO[r.window] || r.window},
      {label: "거래 수", get: (r) => fmt.int(r.n)},
      {label: "승률", get: (r) => fmt.ratio(r.win_rate)},
      {label: "평균 R", get: (r) => ui.signed(fmt.r(r.mean_R), fmt.tone(r.mean_R, fmt.r(r.mean_R)))},
      {label: "운 기준선", get: (r) => fmt.r(r.luck95)},
      {label: "운보다", get: (r) => ui.mark(r.beats_luck, r.beats_luck == null ? "" : r.beats_luck ? "위" : "아래")},
    ], rows, {onRow: (r) => { location.hash = ctx.href("rank", null,
      {strat: shortOf(r.strategy), tf: r.tf, window: r.window || "26w", exit: r.exit || "house", scope: "ALL"}); }}),
    ui.note("운 기준선: 설정 수만큼 무작위 선수를 세웠을 때 그 1등이 낼 법한 평균 R(95%). 이 선 위라야 운이 아닐 가능성이 큽니다. 줄을 누르면 설정 순위로 갑니다."));
}

function switchList(rows) {
  if (!rows || !rows.length) return ui.empty("아직 교체가 없습니다");
  return h("div", {class: "dl-list"}, rows.slice(0, 8).map((d) => h("div", {class: "dl-ev"},
    h("div", {class: "dl-evt"}, h("span", {class: "muted num"}, fmt.kst(d.t_ms)),
      (d.account || d.id) ? h("a", {href: `#/account/${encodeURIComponent(d.account || d.id)}`}, d.name || d.account || d.id) : null,
      h("span", {class: "pp thin"}, d.coin && d.coin !== "ALL" ? fmt.coin(d.coin) : "전체 코인"),
      d.L ? h("span", {class: "pp thin"}, fmt.lev(d.L)) : null),
    h("div", {class: "dl-evb"}, h("span", {class: "mono muted"}, d.from_ko || "—"), " → ", h("b", {class: "mono"}, d.to_ko || "—")),
    d.why_ko ? h("div", {class: "note"}, d.why_ko) : null)));
}

function tradeList(rows, ctx) {
  if (!rows || !rows.length) return ui.empty("아직 거래가 없습니다");
  return h("div", {class: "dl-list"}, rows.slice(0, 8).map((t) => {
    const open = t.status === "open";
    return h("div", {class: "dl-ev"},
      h("div", {class: "dl-evt"}, h("span", {class: "muted num"}, fmt.kst(open ? t.entry_ms : t.exit_ms)),
        t.account ? h("a", {href: `#/account/${encodeURIComponent(t.account)}`}, t.name || t.account) : null),
      h("div", {class: "dl-evb"},
        t.account && t.key ? h("a", {class: "dl-tlink", href: ctx.href("trade", t.account, null, t.key), title: "거래 차트"}, fmt.coin(t.coin))
          : h("b", null, fmt.coin(t.coin)), " ", h("span", {class: ["side", Number(t.side) > 0 ? "long" : "short"]}, sideKo(t.side)), " ",
        h("span", {class: "pp thin"}, fmt.lev(t.L)), " ",
        open ? ui.pill("열림", "accent") : h("span", {class: "muted"}, reasonKo(t.reason)), " ",
        ui.signed(fmt.r(t.R), fmt.tone(t.R, fmt.r(t.R))), " · ",
        ui.signed(fmt.money(t.pnl, true), fmt.tone(t.pnl, fmt.money(t.pnl)))));
  }));
}

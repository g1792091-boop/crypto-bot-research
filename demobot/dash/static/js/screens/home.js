// #/home 홈: the verdict headline ("실전 금지" until something passes), live days and totals, the best / worst
// account lines, mean P&L by account kind and leverage, the ranking leaders against the luck line, recent switches and
// recent trades. home.json + judge.json, every 60 s (drawn again only when the engine wrote a new snapshot).
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {LEVS, KIND_KO, shortOf, tfKo, WINDOW_KO, reasonKo, sideKo, STRAT_KO} from "../labels.js";

export async function mount(el, ctx) {
  ctx.setTitle("홈");
  const verdict = h("section", {class: "card hero dl-verdict", "aria-label": "판정"});
  const stats = h("div", {class: "stats dl-s5"});
  const best = h("div"), worst = h("div"), kinds = h("div"), leaders = h("div"), switches = h("div"), trades = h("div");
  el.append(
    ui.screenHead("홈", "데모 랩 한눈에 보기"),
    verdict, stats,
    h("div", {class: "grid2"},
      ui.card({plate: "잘 되는 줄", sub: "계좌 × 배수 손익 상위 5"}, best),
      ui.card({plate: "안 되는 줄", sub: "계좌 × 배수 손익 하위 5"}, worst)),
    ui.card({plate: "종류별 평균 손익", sub: "배수마다 계좌 평균 (시작 $1,000 대비)"}, kinds),
    ui.card({plate: "순위표 1등", sub: "매매법 × 봉마다 주변 평균 1등과 운 기준선",
      acts: h("a", {class: "btn-line", href: "#/rank"}, "순위표 보기")}, leaders),
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
      put(stats, ui.missing("홈 요약"));
      for (const box of [best, worst, kinds, leaders, switches, trades]) put(box, ui.empty("준비 중"));
      return;
    }
    paintStats(home);
    put(best, lineList(home.best, ctx));
    put(worst, lineList(home.worst, ctx));
    put(kinds, kindTable(home.by_kind));
    put(leaders, leaderTable(home.leaders, ctx));
    put(switches, switchList(home.recent_switches));
    put(trades, tradeList(home.recent_trades));
  }

  function paintVerdict(home, judge) {
    const passed = home && !isMissing(home) && home.totals ? Number(home.totals.passed || 0) : 0;
    const text = judge && !isMissing(judge) && judge.verdict_ko ? judge.verdict_ko : "판정 자료 준비 중";
    const big = passed > 0
      ? h("p", {class: "dl-vbig ok"}, `통과 ${fmt.int(passed)}줄`)
      : h("p", {class: "dl-vbig no"}, "실전 금지");
    put(verdict,
      h("div", {class: "card-h"}, ui.plate("판정"), h("span", {class: "sub"}, "두 가지 기준으로 매일 확인")),
      big,
      h("p", {class: "dl-vline"}, text),
      h("p", {class: "note"}, passed > 0
        ? "통과한 줄이 있어도 실전은 두 분이 정합니다. 판정 화면에서 무엇이 통과했는지 보세요."
        : "아직 어떤 계좌·배수도 기준을 넘지 못했습니다. 넘기 전까지는 실전에 쓰지 않습니다."),
      h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: "#/judge"}, "판정 자세히"),
        h("a", {class: "btn-line", href: "#/howto"}, "기준이 뭔가요?")));
  }

  function paintStats(home) {
    const t = home.totals || {};
    put(stats,
      ui.stat("실시간", home.live_days != null ? `${fmt.num(home.live_days, 1)}일` : "—", home.phase === "warm" ? "과거 채우는 중" : "실시간 시작부터"),
      ui.stat("계좌", fmt.int(t.accounts), "배수 4줄씩"),
      ui.stat("열린 포지션", fmt.int(t.open_positions), "모든 줄 합계"),
      ui.stat("닫힌 거래", fmt.int(t.trades), "모든 줄 합계"),
      ui.stat("통과", fmt.int(t.passed), "우리 기준", Number(t.passed) > 0 ? "dl-good" : null));
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
    {label: "종류", l: true, get: (r) => h("span", {class: "dl-kn"}, h("b", null, r.kind_ko || KIND_KO[r.kind] || r.kind), r.accounts ? h("small", {class: "muted"}, `${r.accounts}개`) : null)},
    ...LEVS.map((L) => ({label: `${L}배`, get: (r) => {
      const v = r.mean_pnl_pct ? r.mean_pnl_pct[String(L)] : null;
      return ui.signed(fmt.pct(v, true), fmt.tone(v, fmt.pct(v)));
    }})),
  ], rows, {cls: "dl-kinds"});
}

function leaderTable(rows, ctx) {
  if (!rows || !rows.length) return ui.empty("순위표 준비 중");
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
    ui.note("운 기준선: 설정 수만큼 무작위 선수를 세웠을 때 그 1등이 낼 법한 평균 R(95%). 이 선 위라야 운이 아닐 가능성이 큽니다. 줄을 누르면 순위표로 갑니다."));
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

function tradeList(rows) {
  if (!rows || !rows.length) return ui.empty("아직 거래가 없습니다");
  return h("div", {class: "dl-list"}, rows.slice(0, 8).map((t) => {
    const open = t.status === "open";
    return h("div", {class: "dl-ev"},
      h("div", {class: "dl-evt"}, h("span", {class: "muted num"}, fmt.kst(open ? t.entry_ms : t.exit_ms)),
        t.account ? h("a", {href: `#/account/${encodeURIComponent(t.account)}`}, t.name || t.account) : null),
      h("div", {class: "dl-evb"},
        h("b", null, fmt.coin(t.coin)), " ", h("span", {class: ["side", Number(t.side) > 0 ? "long" : "short"]}, sideKo(t.side)), " ",
        h("span", {class: "pp thin"}, fmt.lev(t.L)), " ",
        open ? ui.pill("열림", "accent") : h("span", {class: "muted"}, reasonKo(t.reason)), " ",
        ui.signed(fmt.r(t.R), fmt.tone(t.R, fmt.r(t.R))), " · ",
        ui.signed(fmt.money(t.pnl, true), fmt.tone(t.pnl, fmt.money(t.pnl)))));
  }));
}

// #/check 점검 진행: the pre-registered checks of research/fullgrid/WATCH_PREREG.md 3 as they stand today, per pool
// (기존 36, 딥시크): C1 (11/11, stop a pool whose 후보 mean is below both its 기본값 and its 동전), C2 (12/11, and 1/11 if
// it did not pass: mean > 0 with the week-block bootstrap p < 0.05, > 기본값, > 동전, 300 closed 후보 trades), the per
// account basis (CONTRACT.md 2), the warning lights (WATCH_PREREG 3.1) and the per-strategy pools (3.5, from C2 on).
// HONESTY: everything here is a preview on today's numbers, marked 참고; the checkpoint numbers are computed on the day
// by the committed script (WATCH_PREREG 5) and nothing on this screen changes them.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {ROLES, KIND_LONG, tfKo, lineupOn, compareKo} from "../labels.js";
import * as WK from "../whykit.js";

export async function mount(el, ctx) {
  try { await ctx.meta(); } catch (e) { /* codes instead of names */ }
  const time = h("div"), core = h("div"), ds = h("div"), basis = h("div"), lights = h("div"), strat = h("div"), done = h("div");
  const luck = h("div"), pace = h("div");
  let INS = null;
  const head = ui.screenHead("점검 진행", "미리 정한 기준이 오늘 숫자로는 어떤지 (참고) · 판정은 점검 날 한 번");
  const timeCard = ui.card({plate: "점검 일정", sub: "시작 전에 고정 (WATCH_PREREG.md) · 바꾸면 DEVIATIONS.md에 이유와 함께 기록"}, time);
  el.append(
    head,
    done,
    timeCard,
    core, ds,
    ui.card({plate: "후보마다 기준", sub: "30번 이상 거래한 후보: 평균 > 0 · 같은 기간 기본값보다 · 동전보다 (셋 다면 기준 통과)"}, basis),
    ui.card({plate: "운 vs 실력", sub: "후보 여러 개 중 몇 개가 나은지, 운만으로 나오는 범위와 대 보기 (참고)"}, luck),
    ui.card({plate: "경고등", sub: "기존 36 후보: 백테스트로 본 예상 범위의 하위 5%보다 낮으면 켜짐 · 알림일 뿐 판정 아님"}, lights),
    ui.card({plate: "후보마다 속도 · 연패", sub: "5년 시험(2024-01~2026-09) 속도로 본 ‘많아야’ 거래 수와 지금 · 가장 길게 연달아 진 횟수와 그 승률에서 보통인 길이"}, pace),
    ui.card({plate: "매매법별 묶음", sub: "2차 점검부터: 매매법마다 후보를 모아 2차와 같은 세 조건(평균 > 0 · p < 0.05, 기본값 · 동전보다, 거래 300번) + 16개 BH 10%"}, strat));

  // the owner-exit league (owners 10/12) has no 기본값 or 동전 accounts: WATCH_PREREG's checks do not apply to it; the
  // warning lights (the pick's own exit against its backtest band) and the paces still do
  const only = [basis, luck, strat].map((x) => x.closest("section")).filter(Boolean);
  ctx.onLeague((d) => {
    if (!d.accounts || !d.watch) { put(time, ui.none("준비 중")); return; }
    const w = d.watch;
    const owner = lineupOn();
    for (const sec of only) sec.hidden = owner;
    if (owner) {
      const R = LK.road(d);
      head.querySelector(".sub").textContent = "경고등 · 후보마다 속도 · 연패 (참고) · 승자를 가리는 판정은 판정 화면에서 28일째 한 번";
      timeCard.querySelector(".plate").textContent = "일정";
      timeCard.querySelector(".sub").textContent = "판정 규칙은 숫자를 보기 전에 정했습니다 (판정 화면)";
      put(done, null);                        // the candidate league's confirmed 11/11 · 12/11 results do not belong to this league
      put(time, h("p", null, `지금 리그는 청산 비교 리그입니다 (두 분 2026-10-12): 후보마다 계좌 종류 ${fmt.int(ROLES.length)}가지를 같은 신호로 나란히 돌립니다. 기존 점검(11/11 · 12/11 · 1/11)은 이 리그에 하지 않고, 대신 ${R ? R.observe : 14}일째에 숫자만 보고 ${R ? R.decide : 28}일째에 한 번 판정합니다.`),
        LK.roadSteps(d, {cls: "s2a-steps"}),
        h("p", {class: "note"}, "승자는 ", h("a", {href: "#/decision"}, "판정 화면"), "의 규칙으로만 가립니다. 계좌끼리 비교는 ", h("a", {href: "#/compare"}, compareKo()),
          " 화면에 있습니다. 아래 경고등(기존 36 후보의 지금 청산이 백테스트 예상 범위 아래인지)과 속도 · 연패는 참고입니다."));
      put(core, null); put(ds, null);
      paintLights(d);
      put(pace, paceTable(d, INS));
      WK.loadInsight(ctx).then((x) => { if (x !== INS && ctx.alive()) { INS = x; put(pace, paceTable(LK.league(), INS)); } }).catch(() => { /* streaks stay "—" */ });
      return;
    }
    put(time, timeline(w.checkpoints));
    put(core, poolCard("core", w));
    put(ds, poolCard("ds", w));
    paintBasis(d);
    put(luck, WK.luckBody(d));
    paintLights(d);
    put(pace, paceTable(d, INS));
    put(strat, stratTable(w));
    WK.loadInsight(ctx).then((x) => { if (x !== INS && ctx.alive()) { INS = x; put(pace, paceTable(LK.league(), INS)); } }).catch(() => { /* streaks stay "—" */ });
  });

  async function loadConfirmed() {
    if (lineupOn()) { put(done, null); return; }
    let r;
    try { r = await ctx.api("/api/checkpoints"); } catch (e) { return; }
    const dates = (r && r.due) || [];
    if (!dates.length || !r.results) { put(done, null); return; }
    put(done, dates.slice().reverse().map((date) => confirmedCard(r.results[date], date)).filter(Boolean));
  }
  await loadConfirmed();
  ctx.every(300000, loadConfirmed);

  function paintBasis(d) {
    const ix = LK.index(d);
    const by = {ok: [], not_yet: [], early: []};
    for (const c of ix.cands) (by[(ix.judge[c.id] || {}).verdict || "early"] || by.early).push(c);     // "na" (no 기본값 · 동전): not judged
    put(basis, h("div", {class: "stats cl-stats3"},
      ui.stat("기준 통과", fmt.int(by.ok.length), "세 조건 모두", "good"),
      ui.stat("기준 미달", fmt.int(by.not_yet.length), "30번 이상이지만 하나 이상 못 넘음"),
      ui.stat("아직 (30번 전)", fmt.int(by.early.length), "판단하지 않음")),
    by.ok.length ? h("div", {class: "cl-chips"}, h("span", {class: "muted"}, "기준 통과: "),
      by.ok.map((c) => h("a", {class: "pp good", href: `#/account/${encodeURIComponent(c.id)}`}, LK.pickKo(c)))) : null,
    h("p", {class: "note"}, "후보 하나하나의 기준은 참고입니다. 실제 돈을 생각해 볼 수 있는 건 2차 점검에서 묶음이 통과하고 그 매매법도 통과했을 때뿐입니다."));
  }

  /** The owner-exit league's picks are not 23: " (N개 다 차면 약 M개)" from the picks that carry a backtest band. */
  const bandAll = (ix) => {
    const n = ix.cands.filter((c) => c.kind === "core" && c.source && c.source.band).length;
    return n ? ` (${fmt.int(n)}개 다 차면 약 ${fmt.num(n * 0.05, 1)}개)` : "";
  };
  function paintLights(d) {
    const ix = LK.index(d);
    const rows = ix.cands.filter((c) => (ix.judge[c.id] || {}).band);
    const on = rows.filter((c) => ix.judge[c.id].band.below);
    put(lights, h("div", {class: "stats cl-stats3"},
      ui.stat("켜짐", fmt.int(on.length), on.length ? "아래 목록" : "없음", on.length ? "warn" : ""),
      ui.stat("범위 안", fmt.int(rows.length - on.length), "10번 이상 거래한 기존 36 후보 중"),
      ui.stat("우연만으로 켜질 수", `약 ${fmt.num(rows.length * 0.05, 1)}개`, `기준이 있는 후보 ${fmt.int(rows.length)}개 × 5%${lineupOn() ? bandAll(ix) : " (23개 다 차면 약 1개)"}`)),
    on.length ? ui.table([
      {label: "후보", l: true, get: (c) => LK.pickName(c)},
      {label: "기준 거래 수", get: (c) => `${fmt.int(ix.judge[c.id].band.n)}번`},
      {label: "지금 평균", get: (c) => LK.ret(c.mean_ret)},
      {label: "예상 하위 5%", get: (c) => LK.ret(ix.judge[c.id].band.p5)},
      {label: "예상 중간값", get: (c) => LK.ret(ix.judge[c.id].band.median)},
    ], on, {onRow: (c) => { location.hash = `#/account/${encodeURIComponent(c.id)}`; }}) : null);
  }
}

/** 후보마다 속도 · 연패: each pick's trades against the 5-year test pace (whykit pace5y: an upper bound, the test counted
 *  every signal while a league account holds one position at a time) and its losing runs against what its own win rate
 *  makes usual (/api/insight), with its 동전 account's longest run beside it. A table on a PC, one stacked row per pick
 *  on a phone (.pc-ph). */
export function paceTable(d, ins) {
  const ix = LK.index(d);
  const rows = ix.cands.slice().sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "core" ? -1 : 1)
    || LK.stratKo(a.name).localeCompare(LK.stratKo(b.name), "ko") || ["15m", "30m", "1h", "4h"].indexOf(a.tf) - ["15m", "30m", "1h", "4h"].indexOf(b.tf));
  if (!rows.length) return ui.none("준비 중");
  const I = (ins && ins.accounts) || {};
  const cps = ((d.watch || {}).checkpoints || []).slice(0, 2);
  const runCell = (x) => {
    if (!x || !x.n) return h("span", {class: "muted"}, "—");
    const st = x.streak || {};
    const rare = st.rare != null && x.n >= 10 && st.max > st.rare;
    return h("span", null, h("b", {class: ["num", rare ? "pc-slow" : ""]}, `${fmt.int(st.max)}번`),
      x.n >= 10 ? h("small", {class: "muted"}, `보통 ${fmt.int(st.usual)} · 드묾 ${fmt.int(st.rare)}↑`) : h("small", {class: "muted"}, "10번 전"));
  };
  const nowCell = (c) => {
    const p = WK.pace5y(c, d);
    if (!p) return "—";
    return h("span", null, h("span", {class: "num"}, `약 ${fmt.num(p.expect, p.expect < 10 ? 1 : 0)}번`), h("small", {class: "muted"}, `하루 ${fmt.num(p.rate, 2)}번`));
  };
  const cpCell = (c, cp) => {
    const p = WK.pace5y(c, d);
    const x = p && p.at.find((a) => a.ms === cp.ms);
    return x ? `약 ${fmt.int(Math.round(x.n))}번` : "—";
  };
  const day30 = (c) => {
    const p = WK.pace5y(c, d);
    if (!p) return "—";
    if (c.trades >= 30) return "넘음";
    return p.past30 ? h("span", null, `${fmt.mmdd(p.day30)} 지남`, h("small", {class: "muted"}, `실제 ${fmt.int(c.trades || 0)}번`)) : fmt.mmdd(p.day30);
  };
  const curRun = (c) => { const x = I[c.id]; return x && x.n ? `${fmt.int((x.streak || {}).cur || 0)}번` : "—"; };
  const flipRun = (c) => { const x = I[`${c.id}-flip`]; return x && x.n ? `${fmt.int((x.streak || {}).max || 0)}번` : "—"; };
  const table = ui.table([
    {label: "후보", l: true, get: (c) => LK.pickName(c, {code: false})},
    {label: "거래", get: (c) => `${fmt.int(c.trades)}번`},
    {label: "5년 속도면 지금쯤 (많아야)", title: "5년 시험 기간의 거래 수 ÷ 1,004일 × 시작부터 지난 날. 시험은 신호를 모두 셌고 리그는 한 번에 포지션 하나라서 ‘많아야’ 숫자", get: nowCell},
    ...cps.map((cp) => ({label: `5년 속도면 ${fmt.mmdd(cp.ms)}까지 (많아야)`, title: `5년 시험 속도라면 ${cp.ko}(${fmt.mmdd(cp.ms)})까지 쌓일 수 있는 가장 많은 후보 거래 수 (실제 거래 아님)`,
      get: (c) => cpCell(c, cp)})),
    {label: "30번 되는 날 (빨라도)", title: "5년 시험 속도라면 닫힌 거래 30번(후보 하나를 판단하기 시작하는 수)이 되는 가장 이른 날", get: day30},
    {label: "최장 연패", title: "가장 길게 연달아 진 횟수 · 보통 = 이 승률과 거래 수에서 흔한 최장 길이 · 드묾 = 10번 중 1번만 이보다 김", get: (c) => runCell(I[c.id])},
    {label: "지금 연패", get: curRun},
    ...(lineupOn() ? [] : [{label: "동전 최장", title: "같은 후보의 동전 계좌가 가장 길게 연달아 진 횟수 (같은 시각 · 같은 익절·손절)", get: flipRun}]),     // no per-pick 동전 account in the owner-exit league
  ], rows, {cls: "pc-tbl", wrapCls: "pc-pc", onRow: (c) => { location.hash = `#/account/${encodeURIComponent(c.id)}`; }});
  // a phone: one stacked row per pick (the rule bot's phone rows), no sideways scroll
  const phone = h("div", {class: "pc-ph", role: "list"}, rows.map((c) => {
    const p = WK.pace5y(c, d);
    return h("a", {class: "pc-prow", role: "listitem", href: `#/account/${encodeURIComponent(c.id)}`},
      h("span", {class: "pc-pn"}, LK.pickName(c, {code: false}), h("b", {class: "num"}, `${fmt.int(c.trades)}번`)),
      p ? h("span", {class: "pc-pl"}, `5년 속도면 많아야: 지금쯤 약 ${fmt.num(p.expect, p.expect < 10 ? 1 : 0)}번`,
        ...cps.map((cp) => ` · ${fmt.mmdd(cp.ms)}까지 ${cpCell(c, cp)}`),
        c.trades >= 30 ? " · 30번 넘음" : p.past30 ? ` · 30번은 빨라도 ${fmt.mmdd(p.day30)} (지남 · 실제 ${fmt.int(c.trades || 0)}번)` : ` · 30번은 빨라도 ${fmt.mmdd(p.day30)}쯤`)
        : h("span", {class: "pc-pl muted"}, "5년 시험 거래 수 없음"),
      h("span", {class: "pc-pl"}, "최장 연패 ", runCell(I[c.id]), ` · 지금 ${curRun(c)}${lineupOn() ? "" : ` · 동전 최장 ${flipRun(c)}`}`));
  }));
  return h("div", {class: "stack tight"}, table, phone,
    h("p", {class: "note"}, WK.PACE_WHY, " 그래서 실제 거래가 5년 속도보다 적은 건 이상한 일이 아닙니다. ",
      "그 밖에 신호가 덜 나오거나, 손절이 넓어 배수 검사에서 건너뛴 진입이 있어도 적어집니다. ",
      "3R 후보는 보통 3번에 1번쯤 이겨서 6~10번 연달아 지는 일이 흔합니다: ‘보통’ 안의 연패는 이상한 일이 아닙니다. 연패는 계좌마다 최근 200번 기준."),
    h("p", {class: "note"}, lineupOn()
      ? "후보 하나가 한 달 동안 쌓는 거래는 5년 시험 속도로도 대부분 5~20번이라 후보 하나의 숫자는 아직 운이 큽니다. 그래서 판정은 후보 하나가 아니라 같은 신호의 거래 쌍을 모아서 합니다 (판정 화면)."
      : "후보 하나가 1차 점검까지 쌓는 거래는 5년 시험 속도로도 대부분 5~20번이라 후보 하나의 숫자는 아직 운이 큽니다. 후보를 모은 묶음으로 판정하는 이유입니다."));
}

/** A checkpoint's confirmed result (WATCH_PREREG 3, computed like research/fullgrid/diag/watch_check.py on the trades
 *  closed before 00:00 UTC of that date). */
function confirmedCard(res, date) {
  if (!res) return null;
  const c1 = res.checkpoint === "C1";
  const pools = Object.entries(res.pools || {}).map(([kind, p]) => {
    if (p.error) return h("div", {class: "cl-cbox"}, h("b", null, KIND_LONG[kind]), h("p", {class: "muted"}, p.error));
    const verdict = c1 ? (p.c1_stop == null ? ui.pill("거래 없음", "thin") : p.c1_stop ? ui.pill("멈춤", "bad") : ui.pill("계속", "good"))
      : p.c2 && p.c2.pass ? ui.pill("통과", "good") : ui.pill("통과 못 함", "bad");
    const r = p.roles;
    return h("div", {class: "cl-cbox"}, h("div", {class: "cl-cboxh"}, h("b", null, KIND_LONG[kind]), h("span", {class: "grow"}), verdict),
      h("div", {class: "cl-rbars"}, ["cand", "exitonly", "base", "flip"].map((x) => h("div", {class: ["cl-prow", `r-${x}`]},
        LK.roleChip(x), h("span", {class: "num"}, `${fmt.int(r[x].n)}번`), h("span", {class: "num muted"}, r[x].n ? fmt.pct((100 * r[x].wins) / r[x].n, false, 0) : "—"),
        LK.ret(r[x].mean)))),
      c1 ? null : h("ul", {class: "cl-checks"},
        h("li", null, ui.mark(p.c2.positive_p), h("span", null, "평균 > 0, 운 검사 p < 0.05"), h("small", {class: "muted"}, ` · p = ${p.c2.p == null ? "—" : fmt.num(p.c2.p, 3)}`)),
        h("li", null, ui.mark(p.c2.beats_base), h("span", null, "기본값보다")),
        h("li", null, ui.mark(p.c2.beats_flip), h("span", null, "동전보다")),
        h("li", null, ui.mark(p.c2.trades_300), h("span", null, `후보 거래 300번 이상 (${fmt.int(r.cand.n)}번)`))));
  });
  const strat = !c1 && res.strategies ? ui.table([
    {label: "매매법", l: true, get: (x) => h("b", null, LK.stratKo(x.name))},
    {label: "후보 거래", get: (x) => `${fmt.int(x.roles.cand.n)}번`},
    {label: "한 번 평균", get: (x) => LK.ret(x.roles.cand.mean)},
    {label: "p", get: (x) => (x.p == null ? "—" : fmt.num(x.p, 3))},
    {label: "300번", get: (x) => ui.mark(x.trades_300)},
    {label: "p < 0.05", get: (x) => ui.mark(x.positive_p)},
    {label: "BH 10%", get: (x) => ui.mark(x.bh_10)},
    {label: "기본값보다", get: (x) => ui.mark(x.beats_base)},
    {label: "동전보다", get: (x) => ui.mark(x.beats_flip)},
    {label: "통과", get: (x) => (x.pass ? ui.pill("통과", "good") : ui.pill("아님", "thin"))},
  ], Object.entries(res.strategies).map(([name, x]) => ({name, ...x}))) : null;
  const stratErr = !c1 && res.strategies_error ? h("p", {class: "muted"}, res.strategies_error) : null;
  return ui.card({plate: `${res.ko || res.checkpoint} 확정 결과`, sub: `${date} 00:00 UTC (09:00 KST) 전에 닫힌 거래로 · research/fullgrid/diag/watch_check.py와 같은 계산`,
    acts: res.final ? ui.pill("확정", "good") : ui.pill("엔진이 아직 그날까지 처리 중", "warn"), cls: "cl-confirmed"},
  h("div", {class: "s2a-wrap"}, pools), strat, stratErr,
  h("p", {class: "note"}, c1 ? "1차: 후보 평균이 기본값과 동전 둘 다보다 낮은 묶음은 멈춥니다."
    : "2차(·3차): 묶음이 통과하고 그 매매법도 통과해야 두 분이 실제 돈을 검토할 수 있습니다 (1/4 크기 이하, 잃어도 되는 금액)."));
}

function timeline(cps) {
  return h("div", {class: "cl-cps"}, cps.map((c) => {
    const past = c.days_left <= 0;
    return h("div", {class: ["cl-cp", past ? "past" : ""]},
      h("div", {class: "cl-cph"}, h("b", null, c.ko), h("span", {class: "num"}, fmt.date(c.ms)), c.after ? h("span", {class: "muted"}, c.after) : null,
        h("span", {class: "grow"}), past ? ui.pill("지남", "thin") : ui.pill(`D-${Math.ceil(c.days_left)}`, "accent")),
      h("p", null, c.what));
  }));
}

/** One pool's card: its five roles, the C1 rule and the C2 conditions as they stand now (참고). */
function poolCard(kind, w) {
  const p = w.pools[kind];
  if (!p) return ui.card({plate: KIND_LONG[kind]}, ui.none("준비 중"));
  const r = p.roles;
  const max = Math.max(0.001, ...ROLES.map((x) => Math.abs(r[x].mean || 0)));
  const bars = h("div", {class: "cl-rbars"}, ROLES.map((x) => h("div", {class: ["cl-rbar", `r-${x}`]},
    LK.roleChip(x), h("span", {class: "num muted"}, `${fmt.int(r[x].n)}번 · 승률 ${r[x].n ? fmt.pct((100 * r[x].wins) / r[x].n, false, 0) : "—"}`),
    p.money ? divBar(r[x].mean, max) : h("span", {class: "muted"}, "금액 숨김"),
    LK.ret(r[x].mean, {hiddenIf: !p.money}))));
  const c1 = p.c1_stop == null ? h("p", {class: "muted"}, "아직 비교할 거래가 없습니다")
    : h("div", {class: "cl-verdict"}, p.c1_stop ? ui.pill("지금이면: 멈춤 조건에 해당", "bad") : ui.pill("지금이면: 계속", "good"),
      h("span", {class: "muted"}, p.c1_stop ? " 후보 평균이 기본값과 동전 둘 다보다 낮음" : " 후보 평균이 기본값 또는 동전보다 높음"));
  const c2 = p.c2;
  const min = w.min_trades || 300;
  const pText = !p.money ? (c2.p_ok == null ? `주 ${c2.weeks}개 (4주부터 계산)` : c2.p_ok ? "p < 0.05" : "p ≥ 0.05")
    : c2.p == null ? `주 ${fmt.int(c2.weeks)}개 · ${fmt.int(w.min_weeks_p || 4)}주부터 계산` : `p = ${fmt.num(c2.p, 3)} (주 ${fmt.int(c2.weeks)}개)`;
  const checks = [
    ["후보 평균 > 0", c2.positive, null],
    ["운 검사 (주 단위 부트스트랩) p < 0.05", c2.p_ok, pText],
    ["후보 평균 > 기본값 평균", c2.beats_base, null],
    ["후보 평균 > 동전 평균", c2.beats_flip, null],
    [`후보 거래 ${fmt.int(min)}번 이상`, c2.enough, `${fmt.int(r.cand.n)} / ${fmt.int(min)}번`],
  ];
  return ui.card({plate: KIND_LONG[kind], sub: `후보 ${fmt.int(p.picks)}개 · 계좌 ${fmt.int(p.accounts)}개 · 묶음 평균 = 모든 닫힌 거래를 모은 거래 한 번 평균`},
    bars,
    p.sides ? h("div", {class: "cl-sidebox"}, h("span", {class: "muted"}, "후보 거래를 롱 · 숏으로 나누면 (한쪽만 잘 되면 그 방향의 운일 수 있음)"),
      LK.sideSplit(p.sides, {hidden: !p.money})) : null,
    h("div", {class: "s2a-wrap cl-c12"},
      h("div", {class: "cl-cbox"}, h("div", {class: "cl-cboxh"}, ui.plate("1차 11/11"), h("span", {class: "muted"}, "멈출지")), c1,
        h("p", {class: "note"}, "후보 평균이 기본값 평균과 동전 평균 둘 다보다 낮으면 그 묶음을 멈춥니다. 아니면 계속합니다.")),
      h("div", {class: "cl-cbox"}, h("div", {class: "cl-cboxh"}, ui.plate("2차 12/11"), h("span", {class: "muted"}, "통과하려면 다섯 가지 모두"),
        h("span", {class: "grow"}), c2.all ? ui.pill("지금이면 통과", "good") : ui.pill("지금이면 아직", "thin")),
      h("ul", {class: "cl-checks"}, checks.map(([k, ok, extra]) => h("li", null, ui.mark(ok), h("span", null, k),
        extra ? h("small", {class: "muted"}, ` · ${extra}`) : null))),
      ui.progress(Math.min(1, r.cand.n / min), `후보 거래 ${fmt.int(r.cand.n)} / ${fmt.int(min)}번`), LK.paceLine(LK.league(), r.cand.n, min))),
    shares(r, p.money),
    LK.pairedBox(p.paired, {hidden: !p.money}),
    sizeBox(p),
    p.money ? null : h("p", {class: "note"}, "딥시크 금액 숨김 설정입니다 (CANDLEAGUE_DS_MONEY=0): 조건마다 넘었는지만 보입니다."));
}

/** WATCH_PREREG 3.4, reported with C2 (not deciding it): the numbers' share (후보 − 청산만) and the exit's share
 *  (청산만 − 기본값) of the difference from the rule bot's way. */
function shares(r, money) {
  const c = r.cand.mean, x = r.exitonly.mean, b = r.base.mean;
  const line = (label, v, what) => h("div", {class: "cl-share"}, h("b", null, label),
    v == null ? h("span", {class: "muted"}, "—") : money ? LK.ret(v) : LK.vsMark(v > 0), h("span", {class: "muted"}, what));
  return h("div", {class: "cl-sidebox"}, h("span", {class: "muted"}, "함께 보고하는 것 (판정에는 안 씀): 기본값과의 차이가 어디서 왔나"),
    line("숫자 몫", c != null && x != null ? c - x : null, "후보 − 청산만 바꾼 기본값 = 커스텀값(숫자) 덕"),
    line("청산 몫", x != null && b != null ? x - b : null, "청산만 바꾼 기본값 − 기본값 = 익절·손절 덕"));
}

/** WATCH_PREREG 3.4, reported with C2: the 1/4-size accounts' wallets and drawdowns next to the 후보 ones. */
function sizeBox(p) {
  const z = p.size;
  if (!z) return null;
  const cell = (v, kind) => (v == null ? h("span", {class: "muted"}, p.money ? "—" : "숨김") : kind === "$" ? h("b", {class: "num"}, fmt.money(v)) : h("b", {class: "num"}, fmt.pct(v * 100, false, 1)));
  return h("div", {class: "cl-sidebox"}, h("span", {class: "muted"}, "크기: 후보 계좌와 1/4 크기 계좌 (같은 신호 · 증거금 비율 1/4 · 배수는 같은 규칙으로 다시 고름)"),
    h("div", {class: "cl-sizerow hd"}, h("span", null, ""), h("span", null, "닫힌 거래까지 잔고"), h("span", null, "낙폭 중앙값"), h("span", null, "가장 큰 낙폭")),
    ["cand", "quarter"].map((r) => h("div", {class: "cl-sizerow"}, LK.roleChip(r), cell(z[r].wallet_sum, "$"), cell(z[r].dd_median), cell(z[r].dd_max))),
    h("p", {class: "note"}, `계좌 ${fmt.int(z.cand.accounts)}개씩 · 각 ${LK.startUsd()}에서 시작 (합계 시작 ${fmt.money(z.cand.accounts * LK.EQUITY)}) · 점검처럼 닫힌 거래만 셉니다: 열린 포지션의 진입 수수료가 빠진 요약 화면의 잔고와 조금 다를 수 있습니다`));
}

/** A bar from the middle: right = above 0, left = below 0 (its size against max). */
function divBar(v, max) {
  const x = v == null ? 0 : Math.max(-1, Math.min(1, v / max));
  return h("span", {class: "cl-div", "aria-hidden": "true"}, h("i", {class: x >= 0 ? "u" : "d",
    style: {width: `${(Math.abs(x) * 50).toFixed(1)}%`, left: x >= 0 ? "50%" : `${(50 - Math.abs(x) * 50).toFixed(1)}%`}}));
}

function stratTable(w) {
  const rows = Object.entries(w.strategies || {}).map(([name, s]) => ({name, ...s}));
  if (!rows.length) return ui.none("준비 중");
  const lastCp = ((w.checkpoints || []).slice(-1)[0] || {}).ms;
  const paced = rows.map((r) => LK.paceAt(LK.league(), r.n, lastCp));
  const reach = paced.some((v) => v == null) ? null : paced.filter((v) => v >= 300).length;
  rows.sort((a, b) => (a.kind === b.kind ? (b.mean ?? -1) - (a.mean ?? -1) || b.n - a.n : a.kind === "core" ? -1 : 1));
  return h("div", {class: "stack tight"}, ui.table([
    {label: "매매법", l: true, get: (r) => h("span", null, h("b", null, LK.stratKo(r.name)), h("small", {class: "cl-code"}, r.name))},
    {label: "종류", l: true, get: (r) => LK.kindChip(r.kind)},
    {label: "봉", l: true, get: (r) => h("span", {class: "cl-tfs"}, r.tfs.map((t) => h("span", {class: "an-tf"}, tfKo(t))))},
    {label: "후보 거래", get: (r) => h("span", null, `${fmt.int(r.n)}번 `, r.enough ? ui.pill("300번 넘음", "good") : h("small", {class: "muted"}, `/ 300`))},
    {label: "01/11까지", title: "지금까지의 속도가 이어지면 3차 점검(01/11)까지 쌓일 후보 거래 수",
      get: (r) => { const v = LK.paceAt(LK.league(), r.n, lastCp); return v == null ? "—" : h("span", {class: v < 300 ? "cl-pace short" : "num"}, `약 ${fmt.int(v)}번`); }},
    {label: "승률", get: (r) => (r.n ? fmt.pct((100 * r.wins) / r.n, false, 0) : "—")},
    {label: "한 번 평균", get: (r) => LK.ret(r.mean, {hiddenIf: r.kind === "ds" && !(LK.league() || {}).ds_money})},
    {label: "0보다", get: (r) => LK.vsMark(r.positive)},
    {label: "기본값보다", get: (r) => LK.vsMark(r.beats_base)},
    {label: "동전보다", get: (r) => LK.vsMark(r.beats_flip)},
  ], rows, {onRow: (r) => { location.hash = `#/strategies?s=${encodeURIComponent(r.name)}`; }}),
  reach != null ? h("p", {class: reach < rows.length ? "note cl-caveat" : "note"}, `지금 속도면 01/11까지 300번에 닿는 매매법: ${fmt.int(reach)}개 / ${fmt.int(rows.length)}개. ` +
    "300번 전인 매매법은 판정 대상이 아니라서(p = 1로 셈) 통과할 수 없습니다. 이 기준은 미리 정한 규칙의 글자 그대로이고, 바꾸려면 두 분이 1차 점검(11/11) 전에 정해 기록해야 합니다.") : null,
  h("p", {class: "note"}, "매매법 묶음의 판정은 2차 점검부터: 그 매매법의 후보 거래를 모아 2차와 같은 세 조건(평균 > 0이고 운 검사 p < 0.05, 기본값보다 · 동전보다, 거래 300번 이상)과 16개에 걸친 BH 10% 보정. 지금 표는 참고입니다."));
}

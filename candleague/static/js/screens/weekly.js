// #/weekly 흐름 (the rule bot's v4 흐름: 묶음 레이스 + the weeks): per pool (기존 36, 딥시크),
//  * 묶음 레이스: the median wallet of the 후보, 청산만, 기본값 and 동전 accounts from the start, hour by hour, with the
//    동전 accounts' middle half shaded (the band luck alone draws): whether the 후보 stay above it for weeks, not for a
//    lucky day. Data: /api/race (dash.py, summary.race; closed trades only, hidden DeepSeek accounts left out);
//  * each UTC week (Monday 09:00 KST start) of the 후보, 기본값 and 동전 accounts: trades, win rate and the week's mean
//    per trade (bars from the middle), with the week's sum of per-trade results (the unit the C2 bootstrap resamples,
//    WATCH_PREREG 3.4) and the running mean in small print. Data: the snapshot's watch.pools.*.weeks. DeepSeek with its
//    money hidden shows the week's sign only.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {KIND_LONG, ROLE_KO} from "../labels.js";

const ROLES3 = ["cand", "base", "flip"];
const RACE = ["cand", "exitonly", "base", "flip"];

export async function mount(el, ctx) {
  const core = h("div"), ds = h("div"), race = h("div", {class: "rc-pools"});
  el.append(
    ui.screenHead("흐름", "묶음 레이스 (시간에 따른 잔고) · 주마다 후보 · 기본값 · 동전"),
    ui.card({plate: "묶음 레이스", sub: "계좌 역할마다 잔고 중앙값 · 색칠한 띠 = 동전 계좌의 가운데 절반 (운만으로 나오는 범위) · 닫힌 거래 기준"}, race),
    h("p", {class: "note"}, "거래마다 (손익 ÷ 그 직전 지갑)으로 잽니다. 2차 점검의 운 검사는 이 주 단위를 섞어서 2,000번 다시 뽑습니다."),
    core, ds);
  let seen = null;
  async function loadRace(d) {
    if (seen === d.generated_ms) return;
    seen = d.generated_ms;
    let r;
    try { r = await ctx.api("/api/race"); } catch (e) { if (ctx.alive()) put(race, ui.errorBox(e, () => { seen = null; loadRace(LK.league()); })); return; }
    if (!ctx.alive()) return;
    put(race, ["core", "ds"].map((k) => racePool(k, r, d)));
  }
  ctx.onLeague((d) => {
    if (!d.watch) { put(core, ui.none("준비 중")); return; }
    put(core, poolWeeks("core", d.watch.pools.core));
    put(ds, poolWeeks("ds", d.watch.pools.ds));
    loadRace(d);
  });
}

/** One pool's race: the four roles' median wallets and the 동전 band as one chart (lk.js equityLines), the latest
 *  values in words and where the 후보 median stands against the band. */
export function racePool(kind, r, d) {
  const p = r && r.pools ? r.pools[kind] : null;
  const head = (extra) => h("div", {class: "rc-head"}, h("b", null, KIND_LONG[kind]), extra);
  if (!p || !p.money) {
    return h("div", {class: "rc-pool"}, head(null), h("p", {class: "muted"}, kind === "ds" && d && !d.ds_money ? "딥시크 금액 숨김 설정이라 잔고 흐름이 없습니다" : "준비 중"));
  }
  const t = r.t || [];
  const last = t.length - 1;
  const ro = p.roles || {};
  const series = RACE.filter((x) => ro[x]).map((x) => ({role: x, label: ROLE_KO[x], points: t.map((ms, i) => [ms, ro[x].median[i]])}));
  const fl = ro.flip;
  const band = fl && fl.p25 ? {label: "동전 가운데 절반", points: t.map((ms, i) => [ms, fl.p25[i], fl.p75[i]])} : null;
  const cand = ro.cand ? ro.cand.median[last] : null;
  const where = cand == null || !fl ? null : cand > fl.p75[last] ? "above" : cand < fl.p25[last] ? "below" : "inside";
  const trades = ((((d || {}).watch || {}).pools || {})[kind] || {}).roles;
  const nTr = trades && trades.cand ? trades.cand.n : null;
  return h("div", {class: "rc-pool"},
    head(h("span", {class: "muted"}, `후보 ${fmt.int(ro.cand ? ro.cand.n : 0)}개씩 · ${fmt.int(t.length)}칸 (${fmt.dur(r.step_ms / 1000)}마다)`)),
    h("div", {class: "rc-now"}, RACE.filter((x) => ro[x]).map((x) => h("span", null, LK.roleChip(x, x === "exitonly" ? "청산만" : undefined), " ",
      h("span", {class: "num"}, fmt.money(ro[x].median[last])))),
    fl && fl.p25 ? h("span", null, "동전 가운데 절반 ", h("span", {class: "num"}, `${fmt.money(fl.p25[last])} ~ ${fmt.money(fl.p75[last])}`)) : null),
    LK.equityLines(series, {band, label: `${KIND_LONG[kind]} 묶음 레이스`, h: 240, empty: "아직 닫힌 거래가 없습니다"}),
    h("p", {class: "note"}, where == null ? "아직 비교할 거래가 없습니다." : where === "above"
      ? "지금은 후보 중앙값이 동전의 가운데 절반보다 위입니다. 몇 주 동안 계속 위에 있어야 운이 아니라고 볼 수 있습니다 (참고)."
      : where === "below" ? "지금은 후보 중앙값이 동전의 가운데 절반보다 아래입니다 (참고)."
        : "지금은 후보 중앙값이 동전의 가운데 절반 안: 운만으로도 나오는 자리입니다 (참고).",
    nTr != null && nTr < 300 ? ` 후보 거래 ${fmt.int(nTr)}번: 아직 적어서 하루하루 크게 흔들립니다.` : ""));
}

function poolWeeks(kind, p) {
  if (!p) return ui.card({plate: KIND_LONG[kind]}, ui.none("준비 중"));
  const weeks = p.weeks || [];
  if (!weeks.length) return ui.card({plate: KIND_LONG[kind]}, ui.empty("아직 닫힌 거래가 없습니다"));
  // the headline is the week's mean per trade (sum / trades): a sum of per-trade percentages is not a wallet change
  const mean = (x) => (x && x.n && x.sum != null ? x.sum / x.n : null);
  const max = Math.max(0.0001, ...weeks.flatMap((w) => ROLES3.map((r) => Math.abs(mean(w[r]) || 0))));
  const run = {cand: [0, 0], base: [0, 0], flip: [0, 0]};
  const rows = weeks.map((w) => {
    for (const r of ROLES3) { run[r][0] += (w[r] && w[r].sum) || 0; run[r][1] += (w[r] && w[r].n) || 0; }
    return {w, run: Object.fromEntries(ROLES3.map((r) => [r, run[r][1] ? run[r][0] / run[r][1] : null]))};
  });
  return ui.card({plate: KIND_LONG[kind], sub: `${weeks.length}주 · 마지막 주는 아직 진행 중일 수 있음`},
    h("div", {class: "tbl-wrap"}, h("table", {class: "tbl cl-weeks"},
      h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "주 (월요일)"), ROLES3.map((r) => h("th", {scope: "col", colspan: "2"}, LK.roleChip(r))))),
      h("tbody", null, rows.slice().reverse().map(({w, run: rr}) => h("tr", null,
        h("td", {class: "l num"}, fmt.mmdd(w.week_ms)),
        ROLES3.map((r) => {
          const x = w[r] || {n: 0, wins: 0};
          const m = mean(x);
          const cell = p.money
            ? h("span", {class: "cl-wsum"}, bar(m, max), LK.ret(m), h("small", {class: "muted"}, `주 합계 ${LK.retTxt(x.sum, 1)} · 처음부터 평균 ${LK.retTxt(rr[r])}`))
            : h("span", null, x.up == null ? "—" : x.up ? h("span", {class: "up"}, "▲ 플러스") : h("span", {class: "down"}, "▼ 마이너스"));
          return [h("td", {class: "num muted"}, x.n ? `${fmt.int(x.n)}번 · ${fmt.pct((100 * x.wins) / x.n, false, 0)}` : "—"), h("td", null, cell)];
        })))))),
    h("p", {class: "note"}, "큰 숫자 = 그 주에 닫힌 거래의 한 번 평균(지갑 대비). 주 합계 = 그 주 거래마다 %를 더한 값으로 2차 점검 운 검사가 쓰는 단위이고, 지갑이 그만큼 변한 것은 아닙니다. 처음부터 평균 = 첫 주부터 그 주까지 모든 거래의 한 번 평균."));
}

function bar(v, max) {
  const x = v == null ? 0 : Math.max(-1, Math.min(1, v / max));
  return h("span", {class: "cl-div", "aria-hidden": "true"}, h("i", {class: x >= 0 ? "u" : "d",
    style: {width: `${(Math.abs(x) * 50).toFixed(1)}%`, left: x >= 0 ? "50%" : `${(50 - Math.abs(x) * 50).toFixed(1)}%`}}));
}

// #/weekly 주간 흐름: per pool, each UTC week (Monday 09:00 KST start) of the 후보, 기본값 and 동전 accounts: trades, win
// rate and the week's mean per trade (bars from the middle), with the week's sum of per-trade results (the unit the C2
// bootstrap resamples, WATCH_PREREG 3.4) and the running mean in small print. Data: the snapshot's watch.pools.*.weeks. DeepSeek with its money hidden shows the
// week's sign only.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {KIND_LONG} from "../labels.js";

const ROLES3 = ["cand", "base", "flip"];

export async function mount(el, ctx) {
  const core = h("div"), ds = h("div");
  el.append(
    ui.screenHead("주간 흐름", "주마다 후보 · 기본값 · 동전 (월요일 09:00 KST에 새 주)"),
    h("p", {class: "note"}, "거래마다 (손익 ÷ 그 직전 지갑)으로 잽니다. 2차 점검의 운 검사는 이 주 단위를 섞어서 2,000번 다시 뽑습니다."),
    core, ds);
  ctx.onLeague((d) => {
    if (!d.watch) { put(core, ui.none("준비 중")); return; }
    put(core, poolWeeks("core", d.watch.pools.core));
    put(ds, poolWeeks("ds", d.watch.pools.ds));
  });
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

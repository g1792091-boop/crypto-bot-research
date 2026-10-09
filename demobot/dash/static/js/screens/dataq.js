// #/dataq 데이터 점검 (CONTRACT 9.9, dataq.json): is the engine's data whole and on time? Per coin the 15m bars it
// should have and has (since the history start), the newest bar and how late it came, the last funding, the order book
// rows; the seconds each of the last 192 ticks took (a tick with errors in the warning colour), the last errors, the
// open issues, the warm-up's notes and when the ranking last ran. Every 60 s. Text from the engine is text.
// Round 5 stage 2B (the rule bot's v4 서버·비용 look, server-kit.css): the summary card (a status dot and one plain line,
// four health tiles with a coloured edge), the coins in the dense table look with a filling bar of the bars they have,
// the tick times as bars, the errors as v4 time-stamped rows, the issues and the warm-up notes as v4 problem lines.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import * as K from "../live-kit.js";

/** A health tile with a coloured edge (v4 server-kit tile). */
const tile = (o) => h("div", {class: ["s2-tile", o.st || "none"], title: o.title}, h("span", {class: "k"}, o.k), h("b", {class: "v"}, o.v ?? "—"),
  o.s ? h("span", {class: "s"}, o.s) : null);

export async function mount(el, ctx) {
  await K.needCss();
  ctx.setTitle("데이터 점검");
  const sayBox = h("div"), coinBox = h("div"), tickBox = h("div"), errBox = h("div"), issueBox = h("div", {class: "stack tight"});
  const errPg = ui.pager({size: 15, empty: "오류 기록이 없습니다", render: (part) => h("div", {class: "s2-trows lv-elist"}, part.map((e) => h("div", {class: "s2-trow lv-erow"},
    h("span", {class: "t num"}, fmt.kst(e[0])), h("span", {class: "body lv-etext"}, String(e[1] ?? "")))))});
  el.append(ui.screenHead("데이터 점검", "엔진이 받은 자료가 빠짐없고 제때 왔나"),
    sayBox,
    ui.card({plate: "코인별 자료", sub: "15분봉 · 펀딩 · 호가 기록"}, coinBox),
    ui.card({plate: "처리 시간", sub: "최근 192번 (15분마다 한 번, 약 2일) · 막대 = 걸린 초"}, tickBox),
    h("div", {class: "grid2 s2-dqfoot"}, ui.card({plate: "최근 오류", sub: "새것부터 · 최대 50개"}, errBox, errPg.el),
      ui.card({plate: "남은 문제와 과거 채우기 메모"}, issueBox)),
    ui.note("빠진 봉 = 바이낸스가 주지 않았거나 받지 못한 15분봉. 늦음 = 봉이 닫힌 뒤 엔진이 그 봉을 읽기까지 걸린 초. 문제가 생기면 텔레그램 경고도 갑니다."));

  let seen = null;
  async function load() {
    let d;
    try { d = await ctx.api("/api/dataq"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!seen) put(sayBox, ui.errorBox(e, load));
      return;
    }
    const key = d && !isMissing(d) ? String(d.generated_ms) : "missing";
    if (key === seen) return;
    const first = seen == null;
    seen = key;
    if (isMissing(d)) {
      put(sayBox, ui.missing("데이터 점검 자료"));
      [coinBox, tickBox, errBox, issueBox].forEach((b) => put(b));
      errPg.set([]);
      return;
    }
    const coins = d.coins || [], ticks = d.ticks || [], errors = d.errors || [], issues = d.issues || [];
    const missing = coins.reduce((a, c) => a + (Number(c.bars_missing) || 0), 0);
    const lagMax = Math.max(0, ...coins.map((c) => Number(c.lag_s) || 0));
    const errTicks = ticks.filter((t) => Number(t[2]) > 0).length;
    const ok = !issues.length && !errTicks;
    const lv = ok ? "ok" : "warn";
    const rankAgeH = d.rank_ms ? (Date.now() - Number(d.rank_ms)) / 3.6e6 : null;
    put(sayBox, h("section", {class: "card hero s2-sum", "aria-label": "한 줄 요약", dataset: {level: lv}},
      h("div", {class: "card-h"}, ui.plate("한 줄 요약")),
      h("div", {class: ["s2-dotline", "s2-sumline", lv]}, h("i", {"aria-hidden": "true"}),
        h("span", {class: "s2-sumt dl-vline"}, ok ? "자료 정상: 지금 남은 문제가 없습니다." : `확인할 것 ${fmt.int(issues.length)}건 · 오류가 난 처리 ${fmt.int(errTicks)}번 (최근 ${fmt.int(ticks.length)}번 중)`)),
      h("div", {class: "s2-tiles", style: {"--n": "4"}},
        tile({k: "빠진 15분봉", v: fmt.int(missing), s: "7코인 합 (과거 채운 기간 포함)", st: missing ? "bad" : "ok"}),
        tile({k: "가장 늦은 코인", v: `${fmt.num(lagMax, 1)}초`, s: "봉이 닫힌 뒤 읽기까지", st: coins.length ? "ok" : "none"}),
        tile({k: "처리 시간 중간값", v: ticks.length ? `${fmt.num(median(ticks.map((t) => Number(t[1]))), 1)}초` : "—", s: "한 번의 처리에 걸린 시간",
          st: ticks.length ? (errTicks ? "warn" : "ok") : "none"}),
        tile({k: "설정 순위 마지막 계산", v: d.rank_ms ? fmt.ago(d.rank_ms) : "기록 없음", s: d.rank_ms ? `${fmt.kst(d.rank_ms)} KST` : "한 시간마다 돌아야 합니다",
          st: rankAgeH == null ? "none" : rankAgeH > 2 ? "warn" : "ok"}))));
    put(coinBox, coins.length ? ui.table([
      {label: "코인", l: true, get: (c) => h("b", null, fmt.coin(c.coin))},
      {label: "있어야 할 봉", get: (c) => fmt.int(c.bars_expected)},
      {label: "있는 봉", get: (c) => fmt.int(c.bars_have)},
      {label: "채움", l: true, get: (c) => {
        const share = Number(c.bars_expected) > 0 ? Math.min(1, Number(c.bars_have) / Number(c.bars_expected)) : null;
        return h("span", {class: "s2-fill", title: share == null ? "" : fmt.ratio(share, 2)},
          h("span", {class: ["s2-bar", Number(c.bars_missing) ? "" : "up"]}, h("i", {style: {"--w": `${((share ?? 0) * 100).toFixed(1)}%`}})),
          h("small", {class: "muted"}, share == null ? "—" : fmt.ratio(share, 2)));
      }},
      {label: "빠진 봉", get: (c) => (Number(c.bars_missing) ? h("b", {class: "warn-t"}, fmt.int(c.bars_missing)) : h("span", {class: "up"}, "0"))},
      {label: "마지막 봉", get: (c) => h("span", {class: "num"}, fmt.kst(c.last_bar_ms))},
      {label: "늦음", get: (c) => `${fmt.num(c.lag_s, 1)}초`},
      {label: "마지막 펀딩", get: (c) => h("span", {class: "num"}, fmt.kst(c.funding_last_ms))},
      {label: "호가 기록", get: (c) => `${fmt.int(c.depth_rows)}번`},
      {label: "마지막 호가", get: (c) => h("span", {class: "num"}, fmt.kst(c.depth_last_ms))},
    ], coins, {cls: "s2-dense"}) : ui.none());
    if (ticks.length) {
      const secs = ticks.map((t) => Number(t[1]));
      put(tickBox, h("div", {class: "s2-ticks"}, K.barSpark(secs, {w: 600, h: 70, flags: ticks.map((t) => Number(t[2]) > 0), label: "처리마다 걸린 초"})),
        h("div", {class: "lv-tickax"}, h("span", {class: "num"}, fmt.kst(ticks[0][0])), h("span", null,
          `가장 오래 ${fmt.num(Math.max(...secs), 1)}초 · 중간값 ${fmt.num(median(secs), 1)}초 · 빨간 막대 = 오류가 있었던 처리 ${fmt.int(errTicks)}번`),
        h("span", null, "지금")));
    } else put(tickBox, ui.none());
    put(errBox);
    errPg.set(errors, !first);
    put(issueBox, h("p", {class: "s2-sub"}, "지금 남은 문제"),
      issues.length ? h("ul", {class: "s2-lines"}, issues.map((x) => h("li", {class: "warn"}, String(x)))) : h("p", {class: "s2-dotline ok"}, h("i", {"aria-hidden": "true"}), "없음"),
      h("p", {class: "s2-sub"}, "과거 채우기(warm)에서 본 것"),
      (d.warm_issues || []).length ? h("ul", {class: "s2-lines"}, d.warm_issues.map((x) => h("li", {class: "none"}, String(x)))) : h("p", {class: "muted"}, "없음"));
  }
  await load();
  ctx.every(60000, load);
}

function median(xs) {
  const v = xs.filter(Number.isFinite).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

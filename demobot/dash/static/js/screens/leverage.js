// #/leverage 레버리지 비교 (CONTRACT 9.9): every account's four lines grouped by leverage (20 · 30 · 40 · 50배): mean and
// median P&L %, max drawdown, liquidations, skipped entries (the entry checks), ruins, the stop-rule line's P&L and how
// many lines pass "우리 기준"; overall or for one kind, and the mean P&L % of each kind per leverage. accounts.json +
// judge.json every 60 s.
// Round 5 stage 2: the rule bot's v4 board / analysis cards: the kind switch in one bar, one card per leverage with
// its median as a big number that counts to new values (and a bar from 0), the table in the v4 table style with the
// best line's pixel figure, the kinds with their colour swatch, the reading notes behind 펼치기.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {LEVS, KINDS, KIND_KO} from "../labels.js";
import {byKind, divBar} from "../g4.js";

const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
function median(xs) {
  const a = [...xs].sort((x, y) => x - y);
  return a.length ? (a.length % 2 ? a[(a.length - 1) / 2] : (a[a.length / 2 - 1] + a[a.length / 2]) / 2) : null;
}
const nums = (xs) => xs.filter((v) => v != null && Number.isFinite(Number(v))).map(Number);

export async function mount(el, ctx) {
  ctx.setTitle("레버리지 비교");
  let kind = ctx.params.query.kind || local.get("lev-kind", "all");
  const ctrl = h("div");
  const big = h("div");
  const tbl = h("div");
  const kinds = h("div");
  el.append(ui.screenHead("레버리지 비교", "같은 진입, 배수만 다를 때"),
    ctrl,
    h("section", {class: "k4-sec", "aria-label": "배수 4개"}, K4.secRow("배수 4개", "줄마다 $1,000에서 시작 · 가운데 값 = 줄들을 줄 세웠을 때 가운데"), big),
    ui.card({plate: "배수마다", sub: "계좌마다 같은 진입 · 줄마다 $1,000에서 시작"}, tbl),
    ui.card({plate: "종류 × 배수", sub: "종류마다 줄의 평균 손익 %"}, kinds),
    ui.card({plate: "읽는 법"}, ui.disclosure("다섯 가지 펼치기", h("ul", {class: "s2a-dlines"},
      h("li", null, "증거금 = 지갑의 배수% (20배면 지갑의 20%를 걸고 20배로). 배수가 크면 같은 진입에서 이익도 손실도 커집니다."),
      h("li", null, "건너뜀: 손절이 강제청산 가격보다 안쪽에 있어야 들어가는데, 배수가 크면 강제청산 가격이 가까워져서 못 들어가는 신호가 늘어납니다."),
      h("li", null, "파산: 잔고가 $100 아래로 떨어진 횟수 (그때마다 $1,000에서 다시 시작해 기록을 이어 갑니다)."),
      h("li", null, "정지 규칙 손익: 같은 줄에 계좌 −20% · 하루 −5% · 5연패 멈춤을 걸었다면의 손익입니다."),
      h("li", null, "평균은 한두 줄의 큰 수익에 끌려갈 수 있어서, 가운데 값(중앙값)을 함께 봅니다.")))));

  let accts = null, judge = null, seen = null;
  async function load() {
    let a, j;
    try { [a, j] = await Promise.all([ctx.api("/api/accounts"), ctx.api("/api/judge").catch(() => null)]); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!accts) put(tbl, ui.errorBox(e, load));
      return;
    }
    const key = `${a && a.generated_ms}|${j && j.generated_ms}`;
    if (key === seen) return;
    seen = key;
    accts = a;
    judge = j && !isMissing(j) ? j : null;
    paint();
  }

  function paint() {
    if (!accts || isMissing(accts)) { put(ctrl); put(big); put(tbl, ui.missing("계좌 목록")); put(kinds); return; }
    const all = accts.accounts || [];
    const present = KINDS.filter((k) => all.some((a) => a.kind === k.id));
    if (kind !== "all" && !present.some((k) => k.id === kind)) kind = "all";
    put(ctrl, h("div", {class: "s2a-bar"}, h("span", {class: "s2a-barg"}, h("span", {class: "k4-k"}, "계좌"),
      ui.seg([{id: "all", label: "전체"}, ...present.map((k) => ({id: k.id, label: k.ko}))], kind,
        (v) => { kind = v; local.set("lev-kind", v); ctx.setQuery(v === "all" ? {} : {kind: v}); paint(); }, {label: "계좌 종류", cls: "scroll"})),
    h("span", {class: "muted s2a-small"}, kind === "all" ? `모든 계좌 ${fmt.int(all.length)}개` : `${KIND_KO[kind] || kind} ${fmt.int(all.filter((a) => a.kind === kind).length)}개`)));
    const list = kind === "all" ? all : all.filter((a) => a.kind === kind);
    const pass = new Set(((judge && judge.rows) || []).filter((r) => r.ours && r.ours.pass).map((r) => `${r.id}|${r.L}`));
    const per = LEVS.map((L) => {
      const ls = list.map((a) => ({a, x: (a.lines || {})[String(L)]})).filter((y) => y.x);
      const pnl = nums(ls.map((y) => y.x.pnl_pct));
      const dd = nums(ls.map((y) => y.x.max_dd));
      const stops = nums(ls.map((y) => y.x.stops && y.x.stops.pnl_pct));
      const sum = (k) => ls.reduce((s, y) => s + (Number(y.x[k]) || 0), 0);
      return {L, n: ls.length, mean: mean(pnl), median: median(pnl), up: pnl.filter((v) => v > 0).length,
        dd: mean(dd), ddMax: dd.length ? Math.max(...dd) : null, liqs: sum("liqs"), skipped: sum("skipped"), trades: sum("trades"),
        ruins: sum("ruins"), ruinedLines: ls.filter((y) => y.x.ruins > 0 || y.x.ruined).length,
        stops: mean(stops), stopsMedian: median(stops), pass: ls.filter((y) => pass.has(`${y.a.id}|${L}`)).length,
        best: ls.reduce((b, y) => (b && Number(b.x.pnl_pct) >= Number(y.x.pnl_pct) ? b : y), null)};
    });
    const maxAbs = Math.max(5, ...per.flatMap((p) => [p.median, p.mean].filter((v) => v != null).map(Math.abs)));
    put(big, h("div", {class: "s2a-levcards"}, per.map((p) => h("section", {class: "s2a-levc", "aria-label": `${p.L}배`, dataset: {lev: p.L}},
      h("div", {class: "s2a-hrow"}, h("span", {class: "dl-levtag", dataset: {lev: p.L}}, `${p.L}배`), h("span", {class: "muted s2a-small"}, `${fmt.int(p.n)}줄`)),
      h("div", {class: "s2a-levm"}, K4.liveNum(p.median, {format: K4.pctFmt(1), tone: true, cls: "s2a-levn"}), h("small", null, "가운데 손익")),
      divBar(p.median, maxAbs, `가운데 손익 ${fmt.pct(p.median, true)} (가운데 선 = 0)`, true),
      h("p", {class: "s2a-levs"}, h("span", null, "평균 ", h("b", {class: fmt.tone(p.mean, fmt.pct(p.mean, true))}, fmt.pct(p.mean, true))),
        h("span", null, `이익 ${fmt.int(p.up)}/${fmt.int(p.n)}줄`)),
      h("p", {class: "s2a-levs muted"}, `파산한 줄 ${fmt.int(p.ruinedLines)} · 기준 통과 ${fmt.int(p.pass)}`)))));
    const row = (label, get, title) => h("tr", null, h("th", {scope: "row", class: "l", title}, label), per.map((p) => h("td", null, get(p))));
    put(tbl, h("div", {class: "tbl-wrap"}, h("table", {class: "tbl dl-cmp g4-lev4 s2a-tbl"},
      h("thead", null, h("tr", null, h("th", {class: "l"}, ""), per.map((p) => h("th", null, h("span", {class: "dl-levtag", dataset: {lev: p.L}}, `${p.L}배`))))),
      h("tbody", null,
        row("평균 손익", (p) => ui.signed(fmt.pct(p.mean, true), fmt.tone(p.mean, fmt.pct(p.mean)), "b"), "줄들의 손익 % 평균"),
        row("가운데 손익", (p) => ui.signed(fmt.pct(p.median, true), fmt.tone(p.median, fmt.pct(p.median))), "줄들을 줄 세웠을 때 가운데"),
        row("이익 중인 줄", (p) => `${fmt.int(p.up)} / ${fmt.int(p.n)}`),
        row("최대 낙폭 (평균)", (p) => h("span", {class: "dl-kn"}, fmt.ratio(p.dd), h("small", {class: "muted"}, `가장 큰 ${fmt.ratio(p.ddMax, 0)}`))),
        row("강제청산", (p) => fmt.int(p.liqs), "모든 줄 합계"),
        row("건너뜀", (p) => h("span", {class: "dl-kn"}, fmt.int(p.skipped), h("small", {class: "muted"}, p.trades + p.skipped ? `신호의 ${fmt.num(p.skipped / (p.trades + p.skipped) * 100, 0)}%` : "")),
          "진입 검사로 들어가지 못한 신호 (모든 줄 합계)"),
        row("파산", (p) => h("span", {class: "dl-kn"}, `${fmt.int(p.ruins)}번`, h("small", {class: "muted"}, `${fmt.int(p.ruinedLines)}줄`))),
        row("정지 규칙 손익", (p) => h("span", {class: "dl-kn"}, ui.signed(fmt.pct(p.stops, true), fmt.tone(p.stops, fmt.pct(p.stops))),
          h("small", {class: "muted"}, `가운데 ${fmt.pct(p.stopsMedian, true)}`)), "같은 줄에 정지 규칙을 걸었다면 (평균)"),
        row("우리 기준 통과", (p) => (p.pass ? ui.pill(`${fmt.int(p.pass)}줄`, "good") : "0"), "판정의 우리 기준 5개를 모두 넘은 줄"),
        row("가장 좋은 줄", (p) => (p.best ? h("a", {href: ctx.href("account", p.best.a.id), class: "s2a-nm s2a-small", title: p.best.a.id},
          K4.acctFig(p.best.a, 16), K4.acctName(p.best.a), h("b", {class: ["num", fmt.tone(p.best.x.pnl_pct, fmt.pct(p.best.x.pnl_pct, true))]}, fmt.pct(p.best.x.pnl_pct, true))) : "—"))))));
    put(kinds, ui.table([
      {label: "종류", l: true, get: (k) => h("span", {class: "s2a-kn", dataset: {kind: k.id}}, h("i", {class: "k4-sw", "aria-hidden": "true"}), h("b", null, KIND_KO[k.id] || k.ko),
        h("small", {class: "muted"}, `${k.rows.length}개`))},
      ...LEVS.map((L) => ({label: `${L}배`, get: (k) => {
        const v = mean(nums(k.rows.map((a) => ((a.lines || {})[String(L)] || {}).pnl_pct)));
        return ui.signed(fmt.pct(v, true), fmt.tone(v, fmt.pct(v)));
      }})),
    ], byKind(all), {cls: "dl-kinds s2a-tbl"}));
  }

  await load();
  ctx.every(60000, load);
}

// #/account/<id> 계좌 자세히: the account's rule in one line, its four leverage lines, the equity curves
// (lightweight-charts), the settings it runs now (per coin / per leverage when they differ), the switch history
// (교체 기록), open positions and the trade list (filter by leverage). acct/<id>.json every 60 s.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {equityChart, legend} from "../chart.js";
import {LEVS, COINS, KIND_KO, SUB_KO, kindOfId, reasonKo, sideKo, tfKo} from "../labels.js";

const ID_RE = /^[A-Za-z0-9-]{3,40}$/;

export async function mount(el, ctx) {
  const id = ctx.params.arg || "";
  const back = h("a", {class: "btn-line", href: "#/accounts"}, "← 계좌 목록");
  if (!ID_RE.test(id)) {
    el.append(ui.screenHead("계좌"), back, ui.empty("계좌 이름이 맞지 않습니다."));
    return;
  }
  ctx.setTitle("계좌");
  const head = ui.screenHead("계좌", id);
  const title = head.querySelector("h1");
  const sub = head.querySelector(".sub");
  const ruleBox = h("div"), lineBox = h("div", {class: "dl-lines"}), legendBox = h("div");
  const chartBox = h("div", {class: "dl-chart", role: "img", "aria-label": "배수별 잔고 흐름"});
  const nowBox = h("div"), openBox = h("div");
  const decPager = ui.pager({size: 10, empty: "아직 교체가 없습니다", render: (part) => decisionList(part)});
  let tradeLev = "all";
  const tradePager = ui.pager({size: 20, empty: "거래가 없습니다", render: (part) => tradeTable(part)});
  const tradeSeg = ui.seg([{id: "all", label: "전체"}, ...LEVS.map((L) => ({id: String(L), label: `${L}배`}))], tradeLev,
    (v) => { tradeLev = v; if (data) paintTrades(data, false); }, {label: "거래 배수"});

  el.append(head, h("div", {class: "row wrap"}, back), ruleBox, lineBox,
    ui.card({plate: "잔고 흐름", sub: "배수 4줄 · 지갑 + 열린 포지션 평가금 · 점선 = 시작 $1,000"}, chartBox, legendBox),
    ui.card({plate: "지금 쓰는 설정"}, nowBox),
    h("div", {class: "grid2"},
      ui.card({plate: "교체 기록", sub: "새것부터"}, decPager.el),
      ui.card({plate: "열린 포지션", sub: "마크 가격 기준 미실현, 나갈 때 수수료 전"}, openBox)),
    ui.card({plate: "거래 목록", sub: "새것부터 (최근 600건까지)", acts: tradeSeg}, tradePager.el),
    ui.note("모의 계좌: 바이낸스 실제 시세, 수수료·슬리피지·실제 펀딩 포함. 주문은 넣지 않습니다."));

  let chart = null, data = null, seen = null, chartFailed = false;
  async function load() {
    let d;
    try { d = await ctx.api(`/api/account/${encodeURIComponent(id)}`); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!data) put(ruleBox, ui.errorBox(e, load));
      return;
    }
    // the detail file has no generated_ms of its own: its trade count, newest trade, switches and curve ends tell a change
    const key = d && !isMissing(d) ? JSON.stringify([d.generated_ms, (d.trades || []).length, (d.trades || [])[0],
      d.switches, Object.values(d.curves || {}).map((c) => c[c.length - 1])]) : "missing";
    if (key === seen) return;
    seen = key;
    if (isMissing(d)) { put(ruleBox, ui.missing("이 계좌의 자료")); return; }
    const first = !data;
    data = d;
    title.textContent = d.name || id;
    ctx.setTitle(d.name || id);
    const kindKo = KIND_KO[d.kind || kindOfId(d.id)] || "";
    const subKo = d.sub && SUB_KO[d.sub] && SUB_KO[d.sub] !== kindKo ? SUB_KO[d.sub] : "";
    sub.textContent = [kindKo, subKo, tfKo(d.tf)].filter(Boolean).join(" · ");
    paintRule(d);
    paintLines(d);
    await paintChart(d);
    put(nowBox, settingsNow(d.settings_now || []));
    decPager.set(d.decisions || [], !first);
    paintOpen(d);
    paintTrades(d, !first);
  }

  function paintRule(d) {
    put(ruleBox, ui.card({hero: true, plate: "이 계좌의 규칙", cls: "dl-rule"},
      h("p", {class: "dl-ruleline"}, d.rule_ko || "—"),
      h("div", {class: "row wrap dl-rulemeta"},
        h("span", null, h("span", {class: "muted"}, "지금 설정 "), h("b", {class: "mono"}, d.setting_ko || "—")),
        h("span", null, h("span", {class: "muted"}, "교체 "), h("b", null, `${fmt.int(d.switches || 0)}회`)),
        d.last_switch_ms ? h("span", null, h("span", {class: "muted"}, "마지막 교체 "), h("b", null, fmt.kst(d.last_switch_ms))) : null,
        d.strategy ? h("span", {class: "muted mono"}, d.strategy) : null)));
  }

  function paintLines(d) {
    put(lineBox, LEVS.map((L) => {
      const x = (d.lines || {})[String(L)];
      if (!x) return h("div", {class: "stat"}, h("span", {class: "k"}, `${L}배`), h("b", null, "—"));
      const pT = fmt.pct(x.pnl_pct, true);
      return h("div", {class: ["stat", "dl-line", x.ruined ? "dl-ruined" : ""]},
        h("span", {class: "k"}, h("span", {class: "dl-levtag", dataset: {lev: L}}, `${L}배`), x.ruined ? ui.pill("파산", "bad") : null),
        h("b", {class: "num"}, fmt.money(x.equity)),
        h("span", {class: ["num", "dl-lpnl", fmt.tone(x.pnl_pct, pT)]}, `${pT} (${fmt.money(x.pnl, true)})`),
        h("span", {class: "s"}, `거래 ${fmt.int(x.trades)} · 승률 ${fmt.ratio(x.win_rate)} · 평균 ${fmt.r(x.mean_R)}`),
        h("span", {class: "s"}, `최대 낙폭 ${fmt.ratio(x.max_dd)} · 열림 ${fmt.int(x.open)} · 오늘 ${fmt.money(x.today_pnl, true)}`),
        (x.skipped || x.liqs) ? h("span", {class: "s muted"}, `건너뜀 ${fmt.int(x.skipped)} · 강제청산 ${fmt.int(x.liqs)} · 최장 연패 ${fmt.int(x.worst_streak)}`) : null,
        x.setting_ko && x.setting_ko !== d.setting_ko ? h("span", {class: "s mono dl-lset", title: x.setting_ko}, x.setting_ko) : null);
    }));
  }

  async function paintChart(d) {
    const last = Object.fromEntries(LEVS.map((L) => [L, ((d.lines || {})[String(L)] || {}).equity]));
    put(legendBox, legend(LEVS, last));
    if (chartFailed) return;
    try {
      if (!chart) { chart = await equityChart(chartBox, 1000); ctx.signal.addEventListener("abort", () => chart && chart.dispose()); }
      if (!ctx.alive()) return;
      chart.update(d.curves || {}, LEVS);
    } catch (e) {
      chartFailed = true;
      put(chartBox, ui.empty("차트를 그리지 못했습니다."));
    }
  }

  function paintOpen(d) {
    const rows = (d.trades || []).filter((t) => t.status === "open");
    put(openBox, rows.length ? ui.table([
      {label: "코인", l: true, get: (t) => h("span", null, h("b", null, fmt.coin(t.coin)), " ", h("span", {class: ["side", Number(t.side) > 0 ? "long" : "short"]}, sideKo(t.side)))},
      {label: "배수", get: (t) => fmt.lev(t.L)},
      {label: "진입", get: (t) => h("span", {class: "num"}, fmt.num(t.entry, priceDec(t.entry)))},
      {label: "손절", get: (t) => h("span", {class: "num"}, fmt.num(t.stop, priceDec(t.stop)))},
      {label: "증거금", get: (t) => fmt.money(t.margin)},
      {label: "미실현", get: (t) => ui.signed(fmt.money(t.pnl, true), fmt.tone(t.pnl, fmt.money(t.pnl)))},
      {label: "들어간 때", get: (t) => fmt.kst(t.entry_ms)},
    ], rows.slice(0, 40)) : ui.empty("열린 포지션이 없습니다"));
  }

  function paintTrades(d, keep) {
    const all = d.trades || [];
    tradePager.set(tradeLev === "all" ? all : all.filter((t) => String(t.L) === tradeLev), keep);
  }

  await load();
  ctx.every(60000, load);
}

const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };

function settingsNow(rows) {
  if (!rows.length) return ui.empty("설정 정보가 없습니다");
  const same = rows.every((r) => r.setting_ko === rows[0].setting_ko && r.exit_ko === rows[0].exit_ko);
  if (same) {
    return h("p", {class: "dl-now1"}, h("span", {class: "pp thin"}, "모든 코인 · 모든 배수"), " ",
      h("b", {class: "mono"}, rows[0].setting_ko || "—"), h("span", {class: "muted"}, ` · ${rows[0].exit_ko || "—"}`));
  }
  const byLev = rows.some((r) => r.L != null);
  if (!byLev) {
    return ui.table([
      {label: "코인", l: true, get: (r) => h("b", null, r.coin === "ALL" ? "전체" : fmt.coin(r.coin))},
      {label: "설정", l: true, get: (r) => h("span", {class: "mono"}, r.setting_ko || "—")},
      {label: "청산", l: true, get: (r) => r.exit_ko || "—"},
    ], rows);
  }
  // per coin x per leverage (friend rule): one row per coin, one column per leverage
  const coins = [...new Set(rows.map((r) => r.coin))].sort((a, b) => COINS.indexOf(a) - COINS.indexOf(b));
  const cell = (c, L) => rows.find((r) => r.coin === c && Number(r.L) === L);
  return ui.table([
    {label: "코인", l: true, get: (c) => h("b", null, c === "ALL" ? "전체" : fmt.coin(c))},
    ...LEVS.map((L) => ({label: `${L}배`, l: true, get: (c) => {
      const r = cell(c, L);
      return r ? h("span", {class: "dl-nowc"}, h("span", {class: "mono"}, r.setting_ko || "—"), h("small", {class: "muted"}, r.exit_ko || "")) : "—";
    }})),
  ], coins, {cls: "dl-nowtbl"});
}

function decisionList(rows) {
  return h("div", {class: "dl-list"}, rows.map((d) => h("div", {class: "dl-ev"},
    h("div", {class: "dl-evt"}, h("span", {class: "muted num"}, fmt.kst(d.t_ms)),
      h("span", {class: "pp thin"}, d.coin && d.coin !== "ALL" ? fmt.coin(d.coin) : "전체 코인"),
      d.L ? h("span", {class: "pp thin"}, fmt.lev(d.L)) : null),
    h("div", {class: "dl-evb"}, h("span", {class: "mono muted"}, d.from_ko || "—"), " → ", h("b", {class: "mono"}, d.to_ko || "—")),
    d.why_ko ? h("div", {class: "note"}, d.why_ko) : null)));
}

function tradeTable(rows) {
  return ui.table([
    {label: "닫힌 때", l: true, get: (t) => t.status === "open" ? ui.pill("열림", "accent") : h("span", {class: "num"}, fmt.kst(t.exit_ms))},
    {label: "코인", l: true, get: (t) => h("span", null, h("b", null, fmt.coin(t.coin)), " ", h("span", {class: ["side", Number(t.side) > 0 ? "long" : "short"]}, sideKo(t.side)))},
    {label: "배수", get: (t) => fmt.lev(t.L)},
    {label: "진입 → 청산", get: (t) => h("span", {class: "num"}, fmt.num(t.entry, priceDec(t.entry)), " → ", t.exit != null ? fmt.num(t.exit, priceDec(t.exit)) : "—")},
    {label: "이유", get: (t) => reasonKo(t.reason)},
    {label: "R", get: (t) => ui.signed(fmt.r(t.R), fmt.tone(t.R, fmt.r(t.R)))},
    {label: "손익", get: (t) => ui.signed(fmt.money(t.pnl, true), fmt.tone(t.pnl, fmt.money(t.pnl)))},
    {label: "증거금 대비", get: (t) => ui.signed(fmt.ratio(t.roe), fmt.tone(t.roe, fmt.ratio(t.roe)))},
    {label: "설정", l: true, get: (t) => h("span", {class: "muted mono dl-tset", title: `${t.setting_ko || ""} · ${t.exit_ko || ""}`}, t.setting_ko || "—")},
    {label: "들어간 때", get: (t) => h("span", {class: "muted num"}, fmt.kst(t.entry_ms))},
  ], rows);
}

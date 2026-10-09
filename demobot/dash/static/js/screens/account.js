// #/account/<id> 계좌 자세히: the account's rule in one line, its four leverage lines, the equity curves
// (lightweight-charts; with the stop-rule twins, CONTRACT 8.2), the stop-rule comparison per line and the stop events,
// the P&L split into price / fees / funding / open (8.4), the settings it runs now (per coin / per leverage when they
// differ), the switch history (교체 기록), open positions and the trade list (filter by leverage; measured cost, the
// market at entry; a row opens the trade chart #/trade/<id>/<key>). acct/<id>.json every 60 s.
// Round 5 stage 2: the rule bot's v4 계좌 look (account.js / account.css): the profile card with the account's pixel
// character, its timeframe chip and kind chips, the four leverage lines as tiles (the P&L in LED digits, the equity line,
// the counts under it), the stop events behind 펼치기 inside the stop-rule card, switches as calm rows, the tables in the
// v4 table style. Read-only; a missing file shows "준비 중".
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {starBtn} from "../favs.js";
import {equityChart, legend} from "../chart.js";
import {LEVS, COINS, KIND_KO, SUB_KO, kindOfId, reasonKo, sideKo, tfKo, STOP_WHAT_KO, STOP_WHAT_SHORT} from "../labels.js";

const ID_RE = /^[A-Za-z0-9-]{3,40}$/;

export async function mount(el, ctx) {
  const id = ctx.params.arg || "";
  const back = h("a", {class: "btn-line", href: "#/accounts"}, "← 순위표");
  if (!ID_RE.test(id)) {
    el.append(ui.screenHead("계좌"), back, ui.empty("계좌 이름이 맞지 않습니다."));
    return;
  }
  ctx.setTitle("계좌");
  const head = ui.screenHead("계좌", id);
  const title = head.querySelector("h1");
  title.after(starBtn("account", id, {label: id, cls: "dl-hstar"}));       // ★ 즐겨찾기 (round 4)
  const sub = head.querySelector(".sub");
  const ruleBox = h("div"), lineBox = h("div", {class: "s2a-lines"}), legendBox = h("div");
  const chartBox = h("div", {class: "dl-chart", role: "img", "aria-label": "배수별 잔고 흐름"});
  const nowBox = h("div"), openBox = h("div"), stopBox = h("div"), partBox = h("div");
  const decPager = ui.pager({size: 10, empty: "아직 교체가 없습니다", render: (part) => decisionList(part)});
  const evPager = ui.pager({size: 10, empty: "아직 정지 규칙이 걸린 적이 없습니다", render: (part) => stopEventList(part)});
  let tradeLev = "all";
  let chartMode = "plain";
  const modeSeg = ui.seg([{id: "plain", label: "그대로"}, {id: "stops", label: "정지 규칙 적용 시"}, {id: "both", label: "둘 다"}], chartMode,
    (v) => { chartMode = v; if (data) paintChart(data); }, {label: "잔고 흐름 보기"});
  const goTrade = (t) => { location.hash = ctx.href("trade", id, null, t.key); };
  const tradePager = ui.pager({size: 20, empty: "거래가 없습니다", render: (part) => tradeTable(part, goTrade)});
  const tradeSeg = ui.seg([{id: "all", label: "전체"}, ...LEVS.map((L) => ({id: String(L), label: `${L}배`}))], tradeLev,
    (v) => { tradeLev = v; if (data) paintTrades(data, false); }, {label: "거래 배수"});

  // CSV 내려받기 (CONTRACT 9.9): every trade of every line of this account, when the engine has written its file
  const csvSlot = h("span", {class: "muted", title: "엔진이 한 시간마다 계좌별 CSV를 씁니다"}, "CSV 준비 중");
  ctx.api("/api/export").then((x) => {
    if (!ctx.alive() || !x || !Array.isArray(x.ids) || !x.ids.includes(id)) return;
    put(csvSlot, h("a", {class: "btn-line", href: `/api/export/${encodeURIComponent(id)}.csv`, download: true,
      title: "이 계좌의 모든 거래 (배수 4줄) · 엑셀에서 열림 (UTF-8)"}, "CSV 내려받기"));
    csvSlot.className = ""; csvSlot.title = "";
  }).catch(() => {});
  const evCount = h("span", {class: "muted"});
  el.append(head, h("div", {class: "row wrap s2a-acts"}, back, h("a", {class: "btn-line", href: ctx.href("compare", null, {ids: id})}, "다른 계좌와 비교"), csvSlot),
    ruleBox,
    h("section", {class: "k4-sec", "aria-label": "배수 4줄"}, K4.secRow("배수 4줄", "줄마다 $1,000에서 시작 · 같은 진입을 배수만 다르게"), lineBox),
    ui.card({plate: "잔고 흐름", sub: "배수 4줄 · 지갑 + 열린 포지션 평가금 · 점선 가로줄 = 시작 $1,000", acts: modeSeg}, chartBox, legendBox),
    ui.card({plate: "정지 규칙 적용 시", sub: "같은 진입에 정지 규칙(계좌 −20% · 하루 −5% · 5연패)을 걸었다면"}, stopBox,
      ui.disclosure(h("span", null, "정지 기록 펼치기 ", evCount), evPager.el)),
    ui.card({plate: "손익 나눠 보기", sub: "손익 = 가격 차이 − 수수료·슬리피지 + 펀딩 + 열린 포지션"}, partBox),
    ui.card({plate: "지금 쓰는 설정"}, nowBox),
    h("div", {class: "s2a-wrap even"},
      ui.card({plate: "교체 기록", sub: "새것부터"}, decPager.el),
      ui.card({plate: "열린 포지션", sub: "마크 가격 기준 미실현, 나갈 때 수수료 전"}, openBox)),
    ui.card({plate: "거래 목록", sub: "새것부터 (최근 600건까지) · 줄을 누르면 거래 차트", acts: tradeSeg}, tradePager.el),
    h("p", {class: "assume"}, "모의 계좌: 바이낸스 실제 시세, 수수료·슬리피지·실제 펀딩 포함. 주문은 넣지 않습니다."));

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
    paintStops(d);
    paintParts(d);
    evPager.set(Array.isArray(d.stop_events) ? d.stop_events : [], !first);
    evCount.textContent = Array.isArray(d.stop_events) ? `(${fmt.int(d.stop_events.length)}개)` : "(기록 없음)";
    put(nowBox, settingsNow(d.settings_now || []));
    decPager.set(d.decisions || [], !first);
    paintOpen(d);
    paintTrades(d, !first);
  }

  function paintRule(d) {
    const kind = d.kind || kindOfId(d.id);
    const subKo = d.sub && SUB_KO[d.sub] && SUB_KO[d.sub] !== KIND_KO[kind] ? SUB_KO[d.sub] : "";
    put(ruleBox, ui.card({hero: true, cls: "dl-rule s2a-prof", label: "이 계좌의 규칙"},
      h("div", {class: "s2a-profh"}, K4.acctFig({...d, kind}, 48),
        h("div", {class: "s2a-profn"}, h("div", {class: "s2a-hrow"}, ui.plate("이 계좌의 규칙"), h("span", {class: "grow"})),
          h("div", {class: "s2a-chips"}, d.tf ? K4.tfChip(d.tf) : null, h("span", {class: "pp", dataset: {kind}}, h("i", {class: "k4-sw", "aria-hidden": "true"}), KIND_KO[kind] || "기타"),
            subKo ? ui.pill(subKo, "thin") : null, d.strategy ? h("span", {class: "pp thin mono"}, d.strategy) : null))),
      h("p", {class: "dl-ruleline"}, d.rule_ko || "—"),
      h("div", {class: "s2a-rulemeta"},
        h("span", null, h("span", {class: "k4-k"}, "지금 설정"), h("b", {class: "mono"}, d.setting_ko || "—")),
        h("span", null, h("span", {class: "k4-k"}, "교체"), h("b", null, `${fmt.int(d.switches || 0)}회`)),
        d.last_switch_ms ? h("span", null, h("span", {class: "k4-k"}, "마지막 교체"), h("b", null, fmt.kst(d.last_switch_ms))) : null)));
  }

  function paintLines(d) {
    put(lineBox, LEVS.map((L) => {
      const x = (d.lines || {})[String(L)];
      if (!x) return h("div", {class: "s2a-line"}, h("span", {class: "dl-levtag", dataset: {lev: L}}, `${L}배`), h("b", {class: "s2a-lpnl"}, "—"), ui.empty("준비 중"));
      const pT = fmt.pct(x.pnl_pct, true);
      const cv = Array.isArray(x.spark) && x.spark.length > 1 ? x.spark : ((d.curves || {})[String(L)] || []).map((p) => p[1]);
      const step = Math.max(1, Math.floor(cv.length / 80));
      return h("div", {class: ["s2a-line", x.ruined ? "ruined" : ""]},
        h("div", {class: "s2a-hrow"}, h("span", {class: "dl-levtag", dataset: {lev: L}}, `${L}배`), x.ruined ? ui.pill(`파산 ${fmt.int(x.ruins || 1)}번`, "bad") : null),
        h("b", {class: ["s2a-lpnl", "num", fmt.tone(x.pnl_pct, pT)]}, pT),
        h("span", {class: "s2a-lmoney"}, h("b", {class: "num"}, fmt.money(x.equity)), " ",
          h("span", {class: ["num", fmt.tone(x.pnl, fmt.money(x.pnl, true))]}, `(${fmt.money(x.pnl, true)})`)),
        h("span", {class: "s2a-lspark"}, K4.miniSpark(cv.filter((_, i) => i % step === 0 || i === cv.length - 1), {fluid: true, h: 30, base: 1000, label: `${L}배 줄 잔고 흐름`})),
        h("span", {class: "s"}, `거래 ${fmt.int(x.trades)} · 승률 ${fmt.ratio(x.win_rate)} · 평균 ${fmt.r(x.mean_R)}`, K4.smallSample(x.trades) ? [" ", K4.smallSample(x.trades)] : null),
        h("span", {class: "s"}, `최대 낙폭 ${fmt.ratio(x.max_dd)} · 열림 ${fmt.int(x.open)} · 오늘 ${fmt.money(x.today_pnl, true)}`),
        (x.skipped || x.liqs) ? h("span", {class: "s muted"}, `건너뜀 ${fmt.int(x.skipped)} · 강제청산 ${fmt.int(x.liqs)} · 최장 연패 ${fmt.int(x.worst_streak)}`) : null,
        x.stops ? h("span", {class: "s"}, h("span", {class: "muted"}, "정지 규칙이면 "), ui.signed(fmt.pct(x.stops.pnl_pct, true), fmt.tone(x.stops.pnl_pct, fmt.pct(x.stops.pnl_pct, true))),
          x.stops.halted_ms ? h("span", {class: "muted"}, ` · ${fmt.mmdd(x.stops.halted_ms)} 멈춤`) : null) : null,
        x.setting_ko && x.setting_ko !== d.setting_ko ? h("span", {class: "s mono dl-lset", title: x.setting_ko}, x.setting_ko) : null);
    }));
  }

  function paintStops(d) {
    const lines = d.lines || {};
    if (!LEVS.some((L) => (lines[String(L)] || {}).stops)) { put(stopBox, ui.none("준비 중 (엔진이 아직 정지 규칙 줄을 쓰지 않습니다)")); return; }
    const pc = (v) => { const t = fmt.pct(v, true); return ui.signed(t, fmt.tone(v, t)); };
    put(stopBox, ui.table([
      {label: "배수", l: true, get: (L) => h("span", {class: "dl-levtag", dataset: {lev: L}}, `${L}배`)},
      {label: "손익 그대로", get: (L) => pc((lines[L] || {}).pnl_pct)},
      {label: "정지 규칙이면", get: (L) => { const sp = (lines[L] || {}).stops; return sp ? h("b", null, pc(sp.pnl_pct)) : "—"; }},
      {label: "차이", get: (L) => { const x = lines[L] || {}, sp = x.stops; return sp ? pc(Number(sp.pnl_pct) - Number(x.pnl_pct)) : "—"; }},
      {label: "낙폭 그대로 → 정지", get: (L) => { const x = lines[L] || {}, sp = x.stops; return sp ? `${fmt.ratio(x.max_dd)} → ${fmt.ratio(sp.max_dd)}` : "—"; }},
      {label: "거래", get: (L) => { const x = lines[L] || {}, sp = x.stops; return sp ? `${fmt.int(x.trades)} → ${fmt.int(sp.trades)}` : "—"; }},
      {label: "막힌 진입", get: (L) => { const sp = (lines[L] || {}).stops; return sp ? fmt.int(sp.blocked) : "—"; }},
      {label: "멈춤", get: (L) => { const sp = (lines[L] || {}).stops; if (!sp) return "—";
        return h("span", {class: "dl-kn"}, sp.halted_ms ? ui.pill(`${fmt.mmdd(sp.halted_ms)} 영구 정지`, "bad") : h("span", {class: "muted"}, "영구 정지 없음"),
          h("small", {class: "muted"}, `하루 정지 ${fmt.int(sp.day_pauses)}번 · 연패 쉼 ${fmt.int(sp.streak_pauses)}번`)); }},
    ], LEVS.map(String), {cls: "dl-stoptbl s2a-tbl"}),
    ui.note("정지 규칙은 새 진입만 막습니다. 이미 들어간 포지션은 원래대로 나갑니다. 위 잔고 흐름에서 \"정지 규칙 적용 시\"를 누르면 그 줄들의 흐름을 봅니다."));
  }

  function paintParts(d) {
    const lines = d.lines || {};
    if (!LEVS.some((L) => (lines[String(L)] || {}).parts)) { put(partBox, ui.none("준비 중")); return; }
    const m = (v) => { const t = fmt.money(v, true); return ui.signed(t, fmt.tone(v, t)); };
    put(partBox, ui.table([
      {label: "배수", l: true, get: (L) => h("span", {class: "dl-levtag", dataset: {lev: L}}, `${L}배`)},
      {label: "가격 차이로", get: (L) => { const p = (lines[L] || {}).parts; return p ? m(p.gross) : "—"; }},
      {label: "수수료·슬리피지", get: (L) => { const p = (lines[L] || {}).parts; return p ? m(-Math.abs(Number(p.fees) || 0)) : "—"; }},
      {label: "펀딩", get: (L) => { const p = (lines[L] || {}).parts; return p ? m(p.funding) : "—"; }},
      {label: "열린 포지션", get: (L) => { const p = (lines[L] || {}).parts; return p ? (p.open == null ? "—" : m(p.open)) : "—"; }},
      {label: "= 손익", get: (L) => h("b", null, m((lines[L] || {}).pnl))},
      {label: "수수료가 먹은 몫", get: (L) => { const p = (lines[L] || {}).parts; if (!p || !(Number(p.gross) > 0)) return h("span", {class: "muted"}, "—");
        return fmt.ratio(Math.abs(Number(p.fees)) / Number(p.gross), 0); }},
    ], LEVS.map(String), {cls: "dl-parts s2a-tbl"}),
    ui.note("가격 차이·수수료·펀딩은 닫힌 거래만 셉니다. 펀딩 +는 받은 것, −는 낸 것. 수수료에는 가정한 슬리피지(한쪽 0.02%)도 들어 있습니다."));
  }

  async function paintChart(d) {
    const stopsOk = d.curves_stops && typeof d.curves_stops === "object";
    modeSeg.hidden = !stopsOk;                    // an engine without stop-rule lines: only the plain curves
    const mode = stopsOk ? chartMode : "plain";
    const last = Object.fromEntries(LEVS.map((L) => { const x = (d.lines || {})[String(L)] || {}; return [L, mode === "stops" && x.stops ? x.stops.equity : x.equity]; }));
    put(legendBox, legend(LEVS, last), mode === "both" ? h("p", {class: "note"}, "실선 = 그대로 · 점선 = 정지 규칙 적용 시") : null,
      !stopsOk && chartMode !== "plain" ? h("p", {class: "note"}, "정지 규칙 잔고 흐름: 준비 중") : null);
    if (chartFailed) return;
    try {
      if (!chart) { chart = await equityChart(chartBox, 1000); ctx.signal.addEventListener("abort", () => chart && chart.dispose()); }
      if (!ctx.alive()) return;
      chart.update(d.curves || {}, LEVS, stopsOk ? d.curves_stops : null, mode);
    } catch (e) {
      chartFailed = true;
      put(chartBox, ui.empty("차트를 그리지 못했습니다."));
    }
  }

  function paintOpen(d) {
    const rows = (d.trades || []).filter((t) => t.status === "open");
    put(openBox, rows.length ? ui.table([
      {label: "코인", l: true, get: (t) => h("span", null, h("b", null, fmt.coin(t.coin)), " ", h("span", {class: ["side", Number(t.side) > 0 ? "long" : "short"]}, sideKo(t.side)))},
      {label: "배수", get: (t) => h("span", {class: "dl-levtag", dataset: {lev: t.L}}, fmt.lev(t.L))},
      {label: "진입", get: (t) => h("span", {class: "num"}, fmt.num(t.entry, priceDec(t.entry)))},
      {label: "손절", get: (t) => h("span", {class: "num"}, fmt.num(t.stop, priceDec(t.stop)))},
      {label: "증거금", get: (t) => fmt.money(t.margin)},
      {label: "미실현", get: (t) => ui.signed(fmt.money(t.pnl, true), fmt.tone(t.pnl, fmt.money(t.pnl)))},
      {label: "들어간 때", get: (t) => fmt.kst(t.entry_ms)},
    ], rows.slice(0, 40), {onRow: goTrade, cls: "s2a-tbl"}) : ui.empty("열린 포지션이 없습니다"));
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
  return h("div", {class: "s2a-rows", role: "list"}, rows.map((d) => h("div", {class: "s2a-ev", role: "listitem"},
    h("div", {class: "s2a-evh"}, h("span", {class: "s2a-t num"}, fmt.kst(d.t_ms)),
      h("span", {class: "pp thin"}, d.coin && d.coin !== "ALL" ? fmt.coin(d.coin) : "전체 코인"),
      d.L ? h("span", {class: "dl-levtag", dataset: {lev: d.L}}, fmt.lev(d.L)) : null),
    h("div", {class: "s2a-evb"}, h("span", {class: "mono muted"}, d.from_ko || "—"), h("span", {class: "s2a-arrow", "aria-hidden": "true"}, " → "), h("b", {class: "mono"}, d.to_ko || "—")),
    d.why_ko ? h("div", {class: "s2a-why"}, d.why_ko) : null)));
}

function stopEventList(rows) {
  return h("div", {class: "s2a-rows", role: "list"}, rows.map((e) => h("div", {class: "s2a-ev", role: "listitem"},
    h("div", {class: "s2a-evh"}, h("span", {class: "s2a-t num"}, fmt.kst(e.t_ms)), h("span", {class: "dl-levtag", dataset: {lev: e.L}}, `${e.L}배`),
      ui.pill(STOP_WHAT_SHORT[e.what] || String(e.what ?? "—"), e.what === "halt" ? "bad" : "warn")),
    h("div", {class: "s2a-evb"}, STOP_WHAT_KO[e.what] || String(e.what ?? ""), " · ",
      e.until_ms ? `${fmt.kst(e.until_ms)}까지 새 진입 없음` : e.what === "halt" ? "이 줄은 다시 들어가지 않음" : "",
      e.wallet != null ? h("span", {class: "muted"}, ` · 그때 지갑 ${fmt.money(e.wallet)}`) : null))));
}

function tradeTable(rows, goTrade) {
  return ui.table([
    {label: "닫힌 때", l: true, get: (t) => t.status === "open" ? ui.pill("열림", "accent") : h("span", {class: "num"}, fmt.kst(t.exit_ms))},
    {label: "코인", l: true, get: (t) => h("span", null, h("b", null, fmt.coin(t.coin)), " ", h("span", {class: ["side", Number(t.side) > 0 ? "long" : "short"]}, sideKo(t.side)))},
    {label: "배수", get: (t) => h("span", {class: "dl-levtag", dataset: {lev: t.L}}, fmt.lev(t.L))},
    {label: "진입 → 청산", get: (t) => h("span", {class: "num"}, fmt.num(t.entry, priceDec(t.entry)), " → ", t.exit != null ? fmt.num(t.exit, priceDec(t.exit)) : "—")},
    {label: "이유", get: (t) => reasonKo(t.reason)},
    {label: "R", get: (t) => ui.signed(fmt.r(t.R), fmt.tone(t.R, fmt.r(t.R)))},
    {label: "손익", get: (t) => ui.signed(fmt.money(t.pnl, true), fmt.tone(t.pnl, fmt.money(t.pnl)))},
    {label: "증거금 대비", get: (t) => ui.signed(fmt.ratio(t.roe), fmt.tone(t.roe, fmt.ratio(t.roe)))},
    {label: "실제 비용", get: (t) => ui.costCell(t)},
    {label: "그때 시장", l: true, get: (t) => (t.trend || t.vol ? ui.regimeChips(t.trend, t.vol) : h("span", {class: "muted"}, "—"))},
    {label: "설정", l: true, get: (t) => h("span", {class: "muted mono dl-tset", title: `${t.setting_ko || ""} · ${t.exit_ko || ""}`}, t.setting_ko || "—")},
    {label: "들어간 때", get: (t) => h("span", {class: "muted num"}, fmt.kst(t.entry_ms))},
  ], rows, {onRow: goTrade, cls: "dl-trades s2a-tbl"});
}

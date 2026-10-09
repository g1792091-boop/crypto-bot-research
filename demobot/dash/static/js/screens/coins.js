// #/coins?coin=BTCUSD 코인별 (CONTRACT 8.12): how every account line did on one coin: its closed trades, win rate,
// mean R, P&L (closed plus open) and open positions on that coin, best first; above it the seven coins side by side.
// /api/coins (summed on the server from the acct/<id>.json trades, which keep each account's newest 600 trades).
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {COINS, LEVS, KINDS, KIND_KO, kindOfId, tfKo} from "../labels.js";

export async function mount(el, ctx) {
  ctx.setTitle("코인별");
  const saved = local.get("coins", {}) || {};
  const f = {coin: COINS.includes(ctx.params.query.coin) ? ctx.params.query.coin : COINS.includes(saved.coin) ? saved.coin : "BTCUSD",
    lev: saved.lev || "all", kind: saved.kind || "all"};
  const keep = () => { local.set("coins", f); ctx.setQuery({coin: f.coin}); };
  const overBox = h("div");
  const coinSeg = ui.seg(COINS.map((c) => ({id: c, label: fmt.coin(c)})), f.coin, (v) => { f.coin = v; keep(); paint(false); }, {label: "코인", cls: "scroll"});
  const levSeg = ui.seg([{id: "all", label: "전체"}, ...LEVS.map((L) => ({id: String(L), label: `${L}배`}))], f.lev,
    (v) => { f.lev = v; keep(); paint(false); }, {label: "배수"});
  const kindSeg = ui.seg([{id: "all", label: "전체"}, ...KINDS.map((k) => ({id: k.id, label: k.ko}))], f.kind,
    (v) => { f.kind = v; keep(); paint(false); }, {label: "계좌 종류"});
  const sumBox = h("div"), partBox = h("div");
  const pg = ui.pager({size: 25, empty: "이 코인에서 거래한 줄이 없습니다", render: (part) => lineTable(part, ctx)});
  el.append(ui.screenHead("코인별", "코인 하나에서 모든 계좌·배수가 어땠나"),
    ui.card({plate: "코인 7개 한눈에", sub: "모든 줄 합계 · 줄을 누르면 그 코인"}, overBox),
    ui.card({plate: "한 코인", cls: "dl-controls"}, coinSeg,
      h("div", {class: "dl-fields"}, ui.field("배수", levSeg), ui.field("계좌 종류", kindSeg)), sumBox, pg.el, partBox),
    ui.note("손익 = 그 코인에서 닫힌 거래의 손익 + 지금 열린 포지션의 평가 손익 (수수료·슬리피지·펀딩 포함). 주문은 넣지 않습니다."));

  let data = null, seen = null;
  async function load() {
    let d;
    try { d = await ctx.api("/api/coins"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!data) put(overBox, ui.errorBox(e, load));
      return;
    }
    const key = d && !isMissing(d) ? `${d.generated_ms}|${d.coins.map((c) => c.total.trades).join(",")}` : "missing";
    if (key === seen) return;
    const first = seen == null;
    seen = key;
    data = d;
    if (isMissing(d)) {
      put(overBox, ui.missing("계좌 자료"));
      put(sumBox); put(partBox); pg.set([]);
      return;
    }
    paintOverview();
    paint(!first);
  }

  function paintOverview() {
    put(overBox, ui.table([
      {label: "코인", l: true, get: (c) => h("b", null, fmt.coin(c.coin))},
      {label: "거래", get: (c) => fmt.int(c.total.trades)},
      {label: "승률", get: (c) => (c.total.trades ? fmt.ratio(c.total.wins / c.total.trades) : "—")},
      {label: "오른 줄 / 내린 줄", get: (c) => h("span", null, h("span", {class: "up"}, fmt.int(c.total.up)), " / ", h("span", {class: "down"}, fmt.int(c.total.down)))},
      {label: "열림", get: (c) => fmt.int(c.total.open)},
      {label: "손익 합계", get: (c) => ui.signed(fmt.money(c.total.pnl, true), fmt.tone(c.total.pnl, fmt.money(c.total.pnl)), "b")},
    ], data.coins, {onRow: (c) => { f.coin = c.coin; coinSeg.set(c.coin); keep(); paint(false); }, rowCls: (c) => (c.coin === f.coin ? "dl-marked" : "")}));
  }

  function paint(keepPage) {
    if (!data || isMissing(data)) return;
    paintOverview();
    const c = data.coins.find((x) => x.coin === f.coin) || {lines: [], total: {}};
    let rows = c.lines || [];
    if (f.lev !== "all") rows = rows.filter((r) => String(r.L) === f.lev);
    if (f.kind !== "all") rows = rows.filter((r) => (r.kind || kindOfId(r.id)) === f.kind);
    const n = rows.reduce((a, r) => a + (Number(r.trades) || 0), 0), w = rows.reduce((a, r) => a + (Number(r.wins) || 0), 0);
    const pnl = rows.reduce((a, r) => a + (Number(r.pnl) || 0), 0);
    const best = rows[0], worst = rows[rows.length - 1];
    put(sumBox, h("div", {class: "stats dl-s4"},
      ui.stat("보이는 줄", fmt.int(rows.length), `${fmt.coin(f.coin)}에서 거래한 줄`),
      ui.stat("닫힌 거래", fmt.int(n), n ? `승률 ${fmt.ratio(w / n)}` : null),
      ui.stat("손익 합계", ui.signed(fmt.money(pnl, true), fmt.tone(pnl, fmt.money(pnl)), "b"), "보이는 줄 합계"),
      ui.stat("가장 잘 된 줄", h("b", {class: "dl-statname"}, best ? `${best.name} ${fmt.lev(best.L)}` : "—"),
        best && worst && best !== worst ? `가장 안 된 줄: ${worst.name} ${fmt.lev(worst.L)}` : null)));
    const partial = rows.filter((r) => r.partial).length;
    put(partBox, partial ? ui.note(`† 표시 ${fmt.int(partial)}줄: 계좌 파일이 최근 ${fmt.int(data.trade_cap || 600)}건만 남겨서, `
      + "그 계좌는 표시된 날짜 뒤의 거래만 셉니다.") : null);
    pg.set(rows, keepPage);
  }

  await load();
  ctx.every(60000, load);
}

function lineTable(rows, ctx) {
  return ui.table([
    {label: "계좌", l: true, hcls: "dl-c2", cls: "dl-c2 dl-wrap2", get: (r) => h("span", {class: "dl-kn"},
      h("a", {href: ctx.href("account", r.id)}, r.name || r.id, r.partial ? h("span", {class: "muted", title: `${fmt.kst(r.since_ms)} 뒤의 거래만`}, " †") : null),
      h("small", {class: "muted"}, `${KIND_KO[r.kind || kindOfId(r.id)] || "기타"} · ${tfKo(r.tf)}${r.partial ? ` · ${fmt.mmdd(r.since_ms)}부터` : ""}`))},
    {label: "배수", get: (r) => h("span", {class: "dl-levtag", dataset: {lev: r.L}}, `${r.L}배`)},
    {label: "거래", get: (r) => fmt.int(r.trades)},
    {label: "승률", get: (r) => fmt.ratio(r.win_rate)},
    {label: "평균 R", get: (r) => ui.signed(fmt.r(r.mean_R), fmt.tone(r.mean_R, fmt.r(r.mean_R)))},
    {label: "열림", get: (r) => (r.open ? h("span", {class: "pp accent"}, fmt.int(r.open)) : "0")},
    {label: "손익", get: (r) => ui.signed(fmt.money(r.pnl, true), fmt.tone(r.pnl, fmt.money(r.pnl)), "b")},
  ], rows, {cls: "dl-coinlines"});
}

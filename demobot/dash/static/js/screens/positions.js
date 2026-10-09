// #/positions 포지션 (CONTRACT 9.2, 9.8): every open position of every plain line (positions.json), filtered by coin,
// side, account kind and leverage, the totals per coin, and the list (sortable; a row opens the trade chart
// #/trade/<id>/<key>). The P&L follows the live price (/api/live): the snapshot's number plus the move since its last
// 15m close. positions.json every 10 s, the price every 10 s.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {COINS, KINDS, KIND_KO, LEVS, kindOfId, tfKo} from "../labels.js";
import * as K from "../live-kit.js";

export async function mount(el, ctx) {
  await K.needCss();
  ctx.setTitle("포지션");
  const saved = local.get("positions", {}) || {};
  const f = {coin: COINS.includes(ctx.params.query.coin) ? ctx.params.query.coin : saved.coin || "all", side: saved.side || "all",
    kind: saved.kind || "all", lev: saved.lev || "all", sort: saved.sort || {key: "unreal", desc: true}};
  const keep = () => local.set("positions", f);
  const coinSel = ui.select([{id: "all", label: "모든 코인"}, ...COINS.map((c) => ({id: c, label: fmt.coin(c)}))], f.coin,
    (v) => { f.coin = v; keep(); paint(false); }, "코인");
  const sideSeg = ui.seg([{id: "all", label: "전체"}, {id: "long", label: "롱"}, {id: "short", label: "숏"}], f.side,
    (v) => { f.side = v; keep(); paint(false); }, {label: "방향"});
  const kindSel = ui.select([{id: "all", label: "모든 종류"}, ...KINDS.map((k) => ({id: k.id, label: k.ko}))], f.kind,
    (v) => { f.kind = v; keep(); paint(false); }, "계좌 종류");
  const levSeg = ui.seg([{id: "all", label: "전체"}, ...LEVS.map((L) => ({id: String(L), label: `${L}배`}))], f.lev,
    (v) => { f.lev = v; keep(); paint(false); }, {label: "배수"});
  const statBox = h("div"), coinBox = h("div"), listHead = h("p", {class: "note"});
  const pg = ui.pager({size: 40, empty: "조건에 맞는 열린 포지션이 없습니다", render: (part) => listTable(part)});
  const SORTS = [{id: "unreal|1", label: "평가 손익 큰 것부터"}, {id: "unreal|0", label: "평가 손익 작은 것부터"},
    {id: "entry_ms|1", label: "최근 진입부터"}, {id: "dist|0", label: "손절에 가까운 것부터"}, {id: "L|1", label: "배수 큰 것부터"}];
  const sortSel = ui.select(SORTS, `${f.sort.key}|${f.sort.desc ? 1 : 0}`, (v) => {
    const [key, d] = v.split("|"); f.sort = {key, desc: d === "1"}; keep(); paint(false); }, "정렬");
  if (!SORTS.some((x) => x.id === `${f.sort.key}|${f.sort.desc ? 1 : 0}`)) sortSel.value = "unreal|1";
  const liveLine = h("p", {class: "note"});
  el.append(ui.screenHead("포지션", "지금 열려 있는 모든 데모 포지션 (계좌 × 배수마다 한 줄)"),
    ui.card({plate: "거르기", cls: "dl-controls"}, h("div", {class: "dl-fields"},
      ui.field("코인", coinSel), ui.field("방향", sideSeg), ui.field("계좌 종류", kindSel), ui.field("배수", levSeg))),
    statBox,
    ui.card({plate: "코인별 합계", sub: "거른 줄만 · 줄을 누르면 그 코인만"}, coinBox),
    ui.card({plate: "포지션 목록", sub: "제목을 누르면 정렬 · 줄을 누르면 거래 차트"}, h("div", {class: "lv-only-narrow"}, ui.field("정렬", sortSel)), listHead, pg.el),
    liveLine,
    ui.note("평가 손익 = 마지막 15분봉 종가로 잰 엔진의 값(들어갈 때 수수료 포함)에 그 뒤 실시간 가격 움직임을 더한 것. 나갈 때 수수료와 펀딩은 아직 안 뺐습니다. "
      + "손절까지 = 지금 가격에서 손절 가격까지 불리한 쪽으로 움직여야 하는 거리. 주문은 넣지 않습니다."));

  let pos = null, live = null;
  const priceOf = (c) => { const r = live && (live.coins || []).find((x) => x.coin === c); return r && r.ok ? r.price : null; };
  const val = (p) => K.liveUnreal(p, priceOf(p.coin));
  const roe = (p) => (Number(p.margin) ? val(p) / Number(p.margin) : null);

  function filtered(ignoreCoin) {
    return (pos.positions || []).filter((p) => (ignoreCoin || f.coin === "all" || p.coin === f.coin)
      && (f.side === "all" || (f.side === "long") === (Number(p.side) > 0))
      && (f.kind === "all" || (p.kind || kindOfId(p.id)) === f.kind)
      && (f.lev === "all" || String(p.L) === f.lev));
  }

  function paint(keepPage) {
    if (!pos) return;
    if (isMissing(pos)) { put(statBox, ui.missing("포지션 자료")); put(coinBox); pg.set([]); listHead.textContent = ""; return; }
    const all = filtered(true), rows = filtered(false);
    const tot = rows.reduce((a, p) => a + (val(p) || 0), 0), tv = fmt.money(tot, true);
    const L = rows.filter((p) => Number(p.side) > 0).length;
    const entries = K.groupEntries(rows).length;
    const margin = rows.reduce((a, p) => a + (Number(p.margin) || 0), 0);
    put(statBox, h("div", {class: "stats dl-s4"},
      ui.stat("열린 줄", fmt.int(rows.length), `계좌 진입 ${fmt.int(entries)}개 (배수 줄이 진입을 나눠 가짐)`),
      ui.stat("롱 / 숏", h("b", null, h("span", {class: "up"}, fmt.int(L)), " / ", h("span", {class: "down"}, fmt.int(rows.length - L))), "줄 기준"),
      ui.stat("평가 손익 합", ui.signed(tv, fmt.tone(tot, tv), "b"), "실시간 가격 기준"),
      ui.stat("묶인 증거금", fmt.money(margin), "열린 줄의 증거금 합")));
    const per = COINS.map((c) => {
      const xs = all.filter((p) => p.coin === c);
      const u = xs.reduce((a, p) => a + (val(p) || 0), 0);
      return {coin: c, n: xs.length, long: xs.filter((p) => Number(p.side) > 0).length, short: xs.filter((p) => Number(p.side) < 0).length,
        entries: K.groupEntries(xs).length, unreal: u, price: priceOf(c) ?? (xs[0] ? xs[0].last : null)};
    });
    put(coinBox, ui.table([
      {label: "코인", l: true, get: (r) => h("b", null, fmt.coin(r.coin))},
      {label: "평가 손익 합", get: (r) => { const v = fmt.money(r.unreal, true); return r.n ? ui.signed(v, fmt.tone(r.unreal, v), "b") : h("span", {class: "muted"}, "—"); }},
      {label: "롱 / 숏", get: (r) => h("span", null, h("span", {class: "up"}, fmt.int(r.long)), " / ", h("span", {class: "down"}, fmt.int(r.short)))},
      {label: "줄", get: (r) => fmt.int(r.n)},
      {label: "계좌 진입", get: (r) => fmt.int(r.entries)},
      {label: "지금 가격", get: (r) => h("span", {class: "num"}, K.px(r.price))},
    ], per, {onRow: (r) => { f.coin = f.coin === r.coin ? "all" : r.coin; coinSel.value = f.coin; keep(); paint(false); },
      rowCls: (r) => (r.coin === f.coin ? "dl-marked" : "")}));
    const sorted = sortRows(rows);
    listHead.textContent = `${fmt.int(rows.length)}줄 · ${f.coin === "all" ? "모든 코인" : fmt.coin(f.coin)}`;
    pg.set(sorted, keepPage);
  }

  const COLS = [
    {key: "coin", label: "코인", l: true, val: (p) => p.coin, get: (p) => h("b", null, fmt.coin(p.coin))},
    {key: "side", label: "방향", l: true, val: (p) => Number(p.side), get: (p) => K.sideTag(p.side)},
    {key: "name", label: "계좌", l: true, val: (p) => String(p.name || p.id), get: (p) => h("a", {href: ctx.href("account", p.id), class: "lv-an", title: `${p.id} · ${KIND_KO[p.kind] || ""} · ${tfKo(p.tf)}`}, p.name || p.id)},
    {key: "L", label: "배수", val: (p) => Number(p.L), get: (p) => fmt.lev(p.L)},
    {key: "entry_ms", label: "들어간 때", val: (p) => Number(p.entry_ms), get: (p) => h("span", {class: "num"}, fmt.kst(p.entry_ms))},
    {key: "entry", label: "진입가", get: (p) => h("span", {class: "num"}, K.px(p.entry))},
    {key: "now", label: "지금", get: (p) => h("span", {class: "num"}, K.px(priceOf(p.coin) ?? p.last))},
    {key: "stop", label: "손절가", get: (p) => h("span", {class: "num"}, K.px(p.stop))},
    {key: "dist", label: "손절까지", val: (p) => Number(p.stop_dist_pct), get: (p) => h("span", {class: "num warn-t"}, K.stopText(p, priceOf(p.coin)))},
    {key: "target", label: "목표가", get: (p) => (p.target != null ? h("span", {class: "num"}, K.px(p.target)) : h("span", {class: "muted"}, "—"))},
    {key: "margin", label: "증거금", val: (p) => Number(p.margin), get: (p) => fmt.money(p.margin)},
    {key: "unreal", label: "평가 손익", val: (p) => val(p), get: (p) => { const v = fmt.money(val(p), true); return ui.signed(v, fmt.tone(val(p), v)); }},
    {key: "roe", label: "증거금 대비", val: (p) => roe(p), get: (p) => { const v = fmt.ratio(roe(p)); return ui.signed(v, fmt.tone(roe(p), v)); }},
    {key: "R", label: "R", val: (p) => Number(p.R), get: (p) => ui.signed(fmt.r(p.R), fmt.tone(p.R, fmt.r(p.R)))},
    {key: "held", label: "보유", val: (p) => Number(p.held_ms), get: (p) => fmt.dur(Number(p.held_ms) / 1000)},
    {key: "set", label: "설정 · 청산", l: true, get: (p) => h("span", {class: "muted mono dl-tset", title: `${p.setting_ko || ""} · ${p.exit_ko || ""}`}, `${p.setting_ko || "—"} · ${p.exit_ko || "—"}`)},
  ];
  function sortRows(rows) {
    const col = COLS.find((c) => c.key === f.sort.key && c.val);
    if (!col) return rows;
    return [...rows].sort((a, b) => {
      const x = col.val(a), y = col.val(b);
      const nx = x == null || (typeof x === "number" && !Number.isFinite(x)), ny = y == null || (typeof y === "number" && !Number.isFinite(y));
      if (nx || ny) return nx === ny ? 0 : nx ? 1 : -1;
      const c = typeof x === "string" ? x.localeCompare(y, "ko") : x - y;
      return f.sort.desc ? -c : c;
    });
  }
  // a PC: the sortable table; a phone: cards with the key numbers (sorted by the 정렬 picker above them)
  function listTable(part) {
    return h("div", null, h("div", {class: "lv-only-wide"}, K.sortTable(COLS, part, {sort: f.sort, cls: "lv-dense", wrapCls: "lv-ptbl",
      onSort: (s2) => { f.sort = s2; keep(); paint(false); },
      onRow: (p) => { location.hash = K.tradeHref(ctx, p, "positions"); }})),
    h("div", {class: "lv-only-narrow"}, K.posCards(part, {ctx, priceOf, from: "positions"})));
  }

  async function loadPos() {
    let d;
    try { d = await ctx.api("/api/positions"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!pos) put(statBox, ui.errorBox(e, loadPos));
      return;
    }
    const first = !pos;
    pos = d;
    paint(!first);
  }
  async function loadLive() {
    try { live = await ctx.api("/api/live"); } catch (e) { if (e && e.name === "AbortError") return; }
    liveLine.textContent = `가격: ${K.liveNote(live)}`;
    if (pos) paint(true);
  }
  await Promise.all([loadPos(), loadLive()]);
  ctx.every(10000, loadPos);
  ctx.every(10000, loadLive);
}

// #/trades 거래 기록: the newest trades of all accounts (trades.json, newest 300 rows; each leverage line is its own
// row), filtered by account kind, coin and open / closed, with the measured entry cost and the market at entry
// (CONTRACT 8.3 / 8.5). A row opens its trade chart (#/trade/<account>/<key>). Every 60 s.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {COINS, KINDS, LEVS, kindOfId, reasonKo, sideKo} from "../labels.js";

export async function mount(el, ctx) {
  ctx.setTitle("거래 기록");
  const saved = local.get("trades", {}) || {};
  const f = {kind: saved.kind || "all", coin: saved.coin || "all", st: saved.st || "all", lev: saved.lev || "all"};
  const keep = () => local.set("trades", f);
  const kindSeg = ui.seg([{id: "all", label: "전체"}, ...KINDS.map((k) => ({id: k.id, label: k.ko}))], f.kind,
    (v) => { f.kind = v; keep(); apply(false); }, {label: "계좌 종류"});
  const stSeg = ui.seg([{id: "all", label: "전체"}, {id: "open", label: "열림"}, {id: "closed", label: "닫힘"}], f.st,
    (v) => { f.st = v; keep(); apply(false); }, {label: "상태"});
  const coinSel = ui.select([{id: "all", label: "모든 코인"}, ...COINS.map((c) => ({id: c, label: fmt.coin(c)}))], f.coin,
    (v) => { f.coin = v; keep(); apply(false); }, "코인");
  const levSel = ui.select([{id: "all", label: "모든 배수"}, ...LEVS.map((L) => ({id: String(L), label: `${L}배`}))], f.lev,
    (v) => { f.lev = v; keep(); apply(false); }, "배수");
  const count = h("p", {class: "note"});
  const pg = ui.pager({size: 25, empty: "조건에 맞는 거래가 없습니다", render: (part) => tradeTable(part, ctx)});
  const box = h("div");
  el.append(ui.screenHead("거래 기록", "모든 계좌의 최근 거래 (배수마다 한 줄)"),
    ui.card({plate: "거르기", cls: "dl-controls"}, h("div", {class: "dl-fields"},
      ui.field("계좌 종류", kindSeg), ui.field("상태", stSeg), ui.field("코인", coinSel), ui.field("배수", levSel))),
    ui.card({plate: "거래", sub: "줄을 누르면 거래 차트"}, count, box, pg.el),
    ui.note("손익은 수수료·슬리피지·펀딩을 뺀 값입니다. 열린 거래는 마크 가격 기준 미실현(나갈 때 수수료 전). 주문 없음."));

  let rows = null, seen = null;
  function apply(keepPage) {
    if (!rows) return;
    const out = rows.filter((t) => (f.kind === "all" || kindOfId(t.account) === f.kind)
      && (f.coin === "all" || t.coin === f.coin) && (f.st === "all" || t.status === f.st)
      && (f.lev === "all" || String(t.L) === f.lev));
    count.textContent = `최근 ${fmt.int(rows.length)}줄 중 ${fmt.int(out.length)}줄`;
    pg.set(out, keepPage);
  }
  async function load() {
    let d;
    try { d = await ctx.api("/api/trades"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!rows) put(box, ui.errorBox(e, load));
      return;
    }
    if (d && d.generated_ms != null && d.generated_ms === seen) return;
    seen = d ? d.generated_ms : null;
    if (isMissing(d)) { rows = null; put(box, ui.missing("거래 기록")); pg.set([]); return; }
    put(box);
    const first = rows == null;
    rows = d.trades || [];
    apply(!first);
  }
  await load();
  ctx.every(60000, load);
}

const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };

function tradeTable(rows, ctx) {
  return ui.table([
    {label: "때", l: true, get: (t) => h("span", {class: "num"}, fmt.kst(t.status === "open" ? t.entry_ms : t.exit_ms))},
    {label: "계좌", l: true, get: (t) => h("a", {href: ctx.href("account", t.account), class: "dl-tacct"}, t.name || t.account)},
    {label: "코인", l: true, get: (t) => h("span", null, h("b", null, fmt.coin(t.coin)), " ", h("span", {class: ["side", Number(t.side) > 0 ? "long" : "short"]}, sideKo(t.side)))},
    {label: "배수", get: (t) => fmt.lev(t.L)},
    {label: "진입 → 청산", get: (t) => h("span", {class: "num"}, fmt.num(t.entry, priceDec(t.entry)), " → ", t.exit != null ? fmt.num(t.exit, priceDec(t.exit)) : "—")},
    {label: "상태", get: (t) => t.status === "open" ? ui.pill("열림", "accent") : reasonKo(t.reason)},
    {label: "R", get: (t) => ui.signed(fmt.r(t.R), fmt.tone(t.R, fmt.r(t.R)))},
    {label: "손익", get: (t) => ui.signed(fmt.money(t.pnl, true), fmt.tone(t.pnl, fmt.money(t.pnl)))},
    {label: "실제 비용", get: (t) => ui.costCell(t)},
    {label: "그때 시장", l: true, get: (t) => (t.trend || t.vol ? ui.regimeChips(t.trend, t.vol) : h("span", {class: "muted"}, "—"))},
    {label: "설정", l: true, get: (t) => h("span", {class: "muted mono dl-tset", title: `${t.setting_ko || ""} · ${t.exit_ko || ""}`}, t.setting_ko || "—")},
  ], rows, {cls: "dl-trades", onRow: (t) => { if (t.account && t.key) location.hash = ctx.href("trade", t.account, {from: "trades"}, t.key); }});
}

// #/fills 체결 기록: the league's newest closed trades (300, every account, newest first). Two views:
//   목록  the rule bot's 체결 기록 rows (the same rows as 포지션 › 체결 기록: positions-orders.js fillRow / fillSum) with
//         기간 · 결과 · 묶음 · 코인 filters and the sum line
//   표    the dense sortable table (filters 계좌 · 종류 · 코인, a search by strategy name)
// A row opens the terminal on that trade. Data: /api/fills every 30 s + the shared snapshot for names. D11: a hidden
// DeepSeek trade (the server sent no money) is counted only. 설치 뒤 진입만 (js/after.js, the switch under the head): both
// views keep the trades entered after the install, their counts say 설치 뒤만, and a view the switch emptied says how
// many it hid, with the button that turns it off.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import * as LK from "../lk.js";
import {COINS, ROLES, ROLE_KO, ROLE_DESC, sideKo, reasonKo, coinOf, coinShort} from "../labels.js";
import {tradesPane} from "./positions-orders.js";
import {replayHref} from "../why.js";
import {afterBar, afterFills, afterOn, afterSuffix, afterEmpty} from "../after.js";

export const css = "scr/positions.css";

const priceDec = (p) => { const a = Math.abs(Number(p) || 0); return a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1; };
const px = (p) => (fmt.bad(p) ? "—" : fmt.num(p, priceDec(p)));

/** The dense table view (the screen as it was before the rule-bot rows). */
function tableView(ctx) {
  const st = {role: "all", kind: "all", coin: "all", fills: [], loaded: false};
  const info = h("p", {class: "note"});
  const gone = h("div", {class: "ps-gone"});                          // 설치 뒤 진입만 emptied the table: why, and 모두 보기
  const board = K4.boardTable({
    page: 50, sort: {id: "t", dir: -1},
    search: {placeholder: "매매법 찾기", match: (r, s) => `${r.c ? LK.stratKo(r.c.name) : ""} ${r.c ? r.c.name : r.f.account}`.toLowerCase().includes(s)},
    onRow: (r) => { location.hash = `#/terminal?acct=${encodeURIComponent(r.f.account)}&coin=${coinOf(r.f.symbol)}&at=${r.f.entry_time}`; },
    cols: [
      {id: "t", label: "청산 (KST)", l: true, sort: (r) => r.f.exit_time, get: (r) => h("span", {class: "num"}, fmt.kst(r.f.exit_time))},
      {id: "a", label: "계좌", l: true, sort: (r) => (r.c ? LK.stratKo(r.c.name) : r.f.account), get: (r) => (r.c ? LK.pickName(r.c, {code: false}) : r.f.account)},
      {id: "role", label: "종류", l: true, sort: (r) => (r.a ? ROLES.indexOf(r.a.role) : 9), dir: 1, get: (r) => (r.a ? LK.roleChip(r.a.role) : "—")},
      {id: "coin", label: "코인", l: true, sort: (r) => r.f.symbol, get: (r) => h("b", null, coinShort(coinOf(r.f.symbol)))},
      {id: "side", label: "방향", l: true, get: (r) => h("span", {class: ["side", r.f.side > 0 ? "long" : "short"]}, sideKo(r.f.side))},
      {id: "ep", label: "진입가", get: (r) => (r.f.entry_price == null ? "숨김" : px(r.f.entry_price))},
      {id: "xp", label: "청산가", get: (r) => (r.f.exit_price == null ? "숨김" : px(r.f.exit_price))},
      {id: "why", label: "이유", sort: (r) => r.f.exit_reason, get: (r) => h("span", {title: r.a && r.f.exit_reason === "RULE" ? ROLE_DESC[r.a.role] || "" : ""}, reasonKo(r.f.exit_reason))},
      {id: "lev", label: "배수", sort: (r) => r.f.leverage, get: (r) => (r.f.pnl == null && r.f.roe == null ? "—" : r.f.leverage ? `${fmt.int(r.f.leverage)}배` : "—")},
      {id: "roe", label: "증거금 대비", sort: (r) => r.f.roe, get: (r) => (r.f.roe == null ? h("span", {class: "muted"}, "숨김") : h("span", {class: ["num", fmt.tone(r.f.roe)]}, fmt.pct(r.f.roe * 100, true, 1)))},
      {id: "pnl", label: "손익", sort: (r) => r.f.pnl, get: (r) => (r.f.pnl == null ? h("span", {class: "muted"}, "숨김") : h("span", {class: ["num", fmt.tone(r.f.pnl)]}, fmt.money(r.f.pnl, true)))},
      {id: "rp", label: "다시보기", get: (r) => h("a", {class: "dl-tlink", href: replayHref(r.f.account, r.f.entry_time), title: "이 거래를 봉 하나씩 다시 보기",
        onclick: (e) => e.stopPropagation()}, "다시보기")},
    ]});
  const el = h("div", {class: "stack"},
    h("div", {class: "dl-fields"},
      ui.field("계좌", ui.seg([{id: "all", label: "전체"}, ...ROLES.map((r) => ({id: r, label: ROLE_KO[r]}))], st.role, (v) => { st.role = v; paint(); }, {label: "계좌"})),
      ui.field("종류", ui.seg([{id: "all", label: "전체"}, {id: "core", label: "기존 36"}, {id: "ds", label: "딥시크"}], st.kind, (v) => { st.kind = v; paint(); }, {label: "종류"})),
      ui.field("코인", ui.seg([{id: "all", label: "전체"}, ...COINS.map((c) => ({id: c, label: coinShort(c)}))], st.coin, (v) => { st.coin = v; paint(); }, {label: "코인"}))),
    ui.card({plate: "체결", sub: "머리글을 누르면 그 순서로"}, gone, board.el, info));
  function paint() {
    const ix = LK.index();
    const pick = (fs) => fs.map((f) => { const a = ix.byId[f.account]; return {f, a, c: a ? LK.pickOf(a, ix) || a : null}; })
      .filter((r) => (st.role === "all" || (r.a && r.a.role === st.role)) && (st.kind === "all" || (r.a && r.a.kind === st.kind))
        && (st.coin === "all" || coinOf(r.f.symbol) === st.coin));
    const rows = pick(afterFills(st.fills));
    board.set(rows, true);
    const wins = rows.filter((r) => (r.f.pnl != null ? r.f.pnl > 0 : r.f.roe != null ? r.f.roe > 0 : !!r.f.win)).length;
    info.textContent = rows.length ? `${rows.length}건${afterSuffix()} · 이긴 거래 ${wins}건 (${fmt.pct((100 * wins) / rows.length, false, 0)}) · 증거금 대비 = 그 거래의 증거금에 대한 손익` : "";
    // 설치 뒤 진입만 left nothing although the server sent trades that match: say how many it hid, never just "없음"
    const hid = !rows.length && afterOn() && st.loaded ? pick(st.fills).length : 0;
    put(gone, hid ? afterEmpty("설치 뒤에 들어간 닫힌 거래가 아직 없습니다", `조건에 맞는 최근 거래 ${fmt.int(hid)}건은 설치 전에 들어간 것이라 '설치 뒤 진입만'에서 숨겼습니다`) : null);
    board.el.hidden = !!hid;
  }
  async function load() { try { st.fills = (await ctx.api("/api/fills")).fills || []; st.loaded = true; } catch (e) { return; } paint(); }
  return {el, load, paint, get loaded() { return st.loaded; }};
}

export async function mount(el, ctx) {
  el.classList.add("ps-scr", "ps-fills");
  try { await ctx.meta(); } catch (e) { /* codes */ }
  let view = local.get("fills-view", "list") === "table" ? "table" : "list";
  const list = tradesPane(ctx, {coinSeg: true, size: 20, per: "all", perKey: "fills-tper"});
  const table = tableView(ctx);
  const body = h("div");
  const show = () => {
    const v = view === "table" ? table : list;
    put(body, view === "table" ? v.el : ui.card({plate: "체결 기록", sub: "최근 닫힌 거래 · 한 줄을 누르면 터미널에서 그 거래", cls: "ps-fcard"}, v.el));
    if (!v.loaded) v.load(); else if (view === "table") v.paint(); else v.render(true);
  };
  const viewSeg = ui.seg([{id: "list", label: "목록"}, {id: "table", label: "표"}], view, (v) => { view = v; local.set("fills-view", v); show(); }, {label: "보기"});
  const afterEl = afterBar({cls: "ps-after"});
  el.append(ui.screenHead("체결 기록", "후보 리그 전체의 최근 닫힌 거래 300건 · 줄을 누르면 터미널에서 그 거래", viewSeg), afterEl, body,
    h("p", {class: "assume once"}, "모의 · 실제 시세 · 닫힌 거래 손익은 수수료·펀딩·슬리피지 포함 · 주문 버튼 없음"));
  show();
  ctx.onLeague(() => { if (view === "table" && table.loaded) table.paint(); else if (list.loaded) list.render(true); });
  ctx.every(30000, () => (view === "table" ? table.load() : list.load()));
}

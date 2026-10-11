// 포지션 › the two other tabs (copied and adapted from the rule bot's paperbot/dash/static/v4/screens/positions.js order
// rows and positions-kit.js tradeRow / tradeSum; nothing imported from it):
//   손절·잠금 주문  every open position's stop (or lock line, once the stop sits on the profit side) and its take-profit
//                 limit, nearest to the mark first, with what touching it pays. Paper orders: nothing is on an exchange.
//   체결 기록       the league's newest closed trades (/api/fills: 300, every account) with 기간 · 결과 · 묶음 filters, a sum
//                 line and rows; a row opens the 터미널 on that trade. The 체결 기록 screen (fills.js) uses the same rows.
// D11: a hidden DeepSeek position / trade (the server sent no money) is only counted ("개수만", out of the sums).
// 설치 뒤 진입만 (js/after.js): the orders come already filtered by the screen; the 체결 기록 keeps the trades ENTERED after
// the install (one entered before it and closed after it is left out too), its sum line says 설치 뒤만, and a list the
// switch emptied says how many it hid, with the button that turns it off.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {gap, POS_GROUPS, inGroup} from "../poskit.js";
import {markOf, serverNow} from "../live.js";
import {coinShort, coinOf, reasonKo} from "../labels.js";
import {sideTag, nameNode, usdt, dist, kindKo, HIDDEN_KO, HIDDEN_WHY} from "./positions-card.js";
import {afterOn, keepFill, afterTag, afterEmpty} from "../after.js";

const DAY = 86400000, KST = 9 * 3600000;
/** Korea's midnight (ms) of the day ``ms`` falls in. */
export const kstMidnight = (ms) => Math.floor((Number(ms) + KST) / DAY) * DAY - KST;

// ---------------------------------------------------------------- 손절·잠금 주문
/** Orders nearest first: the stop / lock line's distance from the mark now (live) or from the entry (not live). A lock
 *  line measured from the entry is past it on the profit side by design: no distance then (``lockIdle``, never
 *  "닿음"), only where it sits against the entry (``fromEntry``: signed share, + above), and it goes after the stops. */
export function orderList(list, markFn = markOf, live = true) {
  return (list || []).filter((p) => !p.hidden && p.stop != null).map((p) => {
    const m = live ? markFn(p.coin) : Number(p.entry);
    const lockIdle = !live && !!p.stop_is_lock;
    const e = Number(p.entry);
    return {p, lockIdle, d: lockIdle ? null : gap(p.side, m, p.stop), dTp: p.tp == null ? null : -gap(p.side, m, p.tp),
      fromEntry: lockIdle && e ? (Number(p.stop) - e) / e : null};
  }).sort((a, b) => (a.d ?? 9) - (b.d ?? 9) || String(a.p.id).localeCompare(String(b.p.id)));
}

export function orderRow(x, o = {}) {
  const p = x.p;
  const lock = !!p.stop_is_lock;
  const go = () => { location.hash = o.href ? o.href("terminal", null, {acct: p.id, coin: p.coin}) : `#/terminal?acct=${encodeURIComponent(p.id)}&coin=${p.coin}`; };
  return h("div", {class: ["lrow", "click", "ps-orow", lock ? "lock" : ""], role: "listitem", tabindex: "0", title: `${p.id} · 터미널에서 보기`,
    onclick: go, onkeydown: (e) => { if (e.key === "Enter") go(); }},
  h("span", {class: "rk"}, sideTag(p.side)), h("span", {class: "lname"}, nameNode(p)),
  h("span", {class: ["ret", "num", lock ? "up" : ""]}, fmt.price(p.stop)),
  h("span", {class: "meta"}, h("span", null, `${coinShort(p.coin)} · ${fmt.lev(p.lev)}`),
    h("span", null, lock ? "잠금선 (스탑 마켓 · 닿으면 수익)" : "손절 (스탑 마켓)"),
    x.lockIdle ? h("span", {class: "up"}, `잠금 중 · 진입가보다 ${fmt.pct(Math.abs(x.fromEntry || 0) * 100, false, 2)} ${(x.fromEntry || 0) >= 0 ? "위" : "아래"}`)
      : h("span", null, `${o.live === false ? "진입가와" : "지금과"} ${x.d != null && x.d <= 0 ? "닿음" : dist(x.d)}`),
    p.stop_pnl != null ? h("span", {class: fmt.tone(p.stop_pnl)}, `발동 시 ${usdt(p.stop_pnl, true)}`) : null,
    p.tp != null ? h("span", {class: "up"}, `익절 리밋 ${fmt.price(p.tp)}${p.tp_pnl != null ? ` (${usdt(p.tp_pnl, true)})` : ""}`) : null,
    h("span", null, kindKo(p))));
}

/** ordersPane(ctx) -> {el, set(list, markFn, live, keepPage, why, before)}; before: how many open positions the screen's
 *  설치 뒤 진입만 left out (an empty list then says so, with the button that turns it off). */
export function ordersPane(ctx) {
  const pager = ui.pager({size: 12, empty: "걸려 있는 손절·잠금 주문이 없습니다",
    render: (part) => h("div", {class: "ps-list", role: "list"}, part)});
  const note = h("p", {class: "pos-note"});
  const gone = h("div", {class: "ps-gone"});
  const el = h("div", {class: "stack"}, gone, pager.el, note);
  let rowsLive = true, goneN = -1;
  const set = (list, markFn = markOf, live = true, keep = true, why = "엔진이 따라잡는 중", before = 0) => {
    rowsLive = live;
    const ords = orderList(list, markFn, live);
    pager.set(ords.map((x) => orderRow(x, {href: ctx && ctx.href, live: rowsLive})), keep);
    const g = !(list || []).length && before ? before : 0;
    if (g !== goneN) {
      goneN = g;
      put(gone, g ? afterEmpty("설치 뒤에 들어간 포지션의 주문이 아직 없습니다", `열린 포지션 ${fmt.int(g)}개는 설치 전에 들어간 것이라 '설치 뒤 진입만'에서 숨겼습니다`) : null);
    }
    pager.el.hidden = !!g;
    const hid = (list || []).filter((p) => p.hidden).length;
    note.textContent = (live ? "지금 가격과 가까운 주문이 위. " : `${why}이라 진입가에서 잰 거리입니다. `) +
      "발동 시 손익은 나갈 때 수수료 전입니다. 모의 주문이라 거래소에는 아무것도 걸려 있지 않습니다 (엔진이 5분마다 1분봉으로 확인)." +
      (hid ? ` 딥시크 ${fmt.int(hid)}개는 가격이 숨겨져 빠짐 (${HIDDEN_KO}).` : "") + (afterOn() ? " 설치 뒤만 (설치 뒤에 들어간 포지션의 주문)." : "");
  };
  return {el, set};
}

// ---------------------------------------------------------------- 체결 기록
const isHidden = (f, a) => (f.pnl == null && f.roe == null) || (a ? LK.dsHidden(a) : false);
const winOf = (f) => (f.pnl != null ? f.pnl > 0 : f.roe != null ? f.roe > 0 : !!f.win);

/** A closed trade as one list row (tap -> the 터미널 on that trade). f: /api/fills row; a: its league account. */
export function fillRow(f, a, o = {}) {
  const now = o.now || serverNow();
  const today = f.exit_time >= kstMidnight(now);
  const hid = isHidden(f, a);
  const pk = a ? LK.pickOf(a) : null;
  const nm = a ? nameNode({...a, pick: pk ? pk.id : a.id}) : h("span", {class: "an"}, h("span", {class: "an-n"}, f.account));
  const go = () => {
    const q = {acct: f.account, coin: coinOf(f.symbol), at: f.entry_time};
    location.hash = o.href ? o.href("terminal", null, q) : `#/terminal?${new URLSearchParams(q)}`;
  };
  return h("div", {class: ["lrow", "click", "ps-trow", hid ? "ps-hid" : ""], role: "listitem", tabindex: "0", title: `${f.account} · 터미널에서 이 거래`,
    onclick: go, onkeydown: (e) => { if (e.key === "Enter") go(); }},
  h("span", {class: "rk"}, today ? fmt.hm(f.exit_time) : fmt.kst(f.exit_time)),
  h("span", {class: "lname"}, nm),
  hid ? h("span", {class: "ret muted", title: HIDDEN_WHY}, HIDDEN_KO) : h("span", {class: ["ret", "num", fmt.tone(f.pnl)]}, usdt(f.pnl, true)),
  h("span", {class: "meta"}, h("span", null, coinShort(coinOf(f.symbol))), sideTag(f.side),
    hid ? null : h("span", null, fmt.lev(f.leverage)),
    h("span", {class: f.exit_reason === "LIQ" ? "down" : ""}, reasonKo(f.exit_reason)),
    hid ? h("span", null, winOf(f) ? "이김" : "짐") : h("span", {class: fmt.tone(f.roe)}, `ROE ${fmt.pct(f.roe * 100, true, 1)}`),
    hid || f.entry_price == null ? null : h("span", {class: "num"}, `${fmt.price(f.entry_price)} → ${fmt.price(f.exit_price)}`),
    a ? h("span", null, kindKo(a)) : null));
}

/** "N건 · 합계 +12.30 USDT · 이긴 거래 a · 강제청산 b · 딥시크 n건 (개수만)" (hidden trades counted only). */
export function fillSum(rows, byId = {}) {
  const hid = rows.filter((r) => isHidden(r, byId[r.account]));
  const money = hid.length ? rows.filter((r) => !isHidden(r, byId[r.account])) : rows;
  const tot = money.reduce((s0, t) => s0 + (Number(t.pnl) || 0), 0), wins = money.filter((t) => t.pnl > 0).length;
  const liq = rows.filter((t) => t.exit_reason === "LIQ").length;
  return h("p", {class: "ps-sumline"}, `${fmt.int(money.length)}건 · 합계 `, h("b", {class: ["num", fmt.tone(tot)]}, usdt(tot, true)),
    ` · 이긴 거래 ${fmt.int(wins)}`, money.length ? ` (${fmt.pct((100 * wins) / money.length, false, 0)})` : "",
    liq ? h("span", {class: "down"}, ` · 강제청산 ${fmt.int(liq)}`) : null,
    hid.length ? h("span", {class: "muted", title: HIDDEN_WHY}, ` · 딥시크 ${fmt.int(hid.length)}건 (${HIDDEN_KO}, 합계에서 뺌)`) : null);
}

/**
 * tradesPane(ctx, {coin: () => "BTCUSD" | "", grp, per, perKey, coinSeg: bool, size}) -> {el, load(), render(), loaded}: the 체결 기록
 * list with its own filters (기간 · 결과 · 묶음 starting at grp, and a coin row when coinSeg). Loads /api/fills when asked.
 */
export function tradesPane(ctx, o = {}) {
  const perKey = o.perKey || "ps-tper";
  const st = {per: local.get(perKey, o.per || "today") === "all" ? "all" : "today", res: "all", grp: POS_GROUPS.some((g) => g.id === o.grp) ? o.grp : "all",
    coin: "", fills: null, err: null, busy: false};
  const perSeg = ui.seg([{id: "today", label: "오늘"}, {id: "all", label: "최근 300건"}], st.per,
    (v) => { st.per = v; local.set(perKey, v); render(false); }, {label: "기간"});
  const resSeg = ui.seg([{id: "all", label: "전부"}, {id: "win", label: "수익"}, {id: "loss", label: "손실"}, {id: "liq", label: "강제청산"}], st.res,
    (v) => { st.res = v; render(false); }, {label: "결과"});
  const grpSel = ui.select(POS_GROUPS.map((g) => ({id: g.id, label: g.id === "all" ? "모든 묶음" : g.ko})), st.grp, (v) => { st.grp = v; render(false); }, "묶음");
  const coinSeg = o.coinSeg ? ui.seg([{id: "", label: "모든 코인"}, ...["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"].map((c) => ({id: c, label: coinShort(c)}))],
    st.coin, (v) => { st.coin = v; render(false); }, {label: "코인", cls: "scroll"}) : null;
  const sum = h("div");
  const note = h("p", {class: "pos-note"});
  const gone = h("div", {class: "ps-gone"});                          // 설치 뒤 진입만 emptied the list: why, and 모두 보기
  const pager = ui.pager({size: o.size || 12, empty: "조건에 맞는 체결이 없습니다", render: (part) => h("div", {class: "ps-list", role: "list"}, part)});
  const el = h("div", {class: "stack"}, h("div", {class: "row wrap ps-filters"}, perSeg, resSeg, grpSel), coinSeg, sum, gone, pager.el, note);
  async function load() {
    if (st.busy) return;
    st.busy = true;
    if (!st.fills) put(sum, h("p", {class: "pos-note"}, "불러오는 중"));
    try {
      const d = await ctx.api("/api/fills");
      st.fills = (d && d.fills) || [];
      st.err = null;
    } catch (e) {
      if (e && e.name === "AbortError") { st.busy = false; return; }
      st.err = e;
    }
    st.busy = false;
    if (ctx.alive()) render(true);
  }
  /** the rows the filters keep (all: without 설치 뒤 진입만, to say how many it hid) */
  function rows(all = false) {
    const ix = LK.index();
    const day0 = kstMidnight(serverNow());
    const coin = o.coin ? o.coin() : st.coin;
    const after = !all && afterOn();
    return (st.fills || []).filter((f) => {
      const a = ix.byId[f.account];
      if (after && !keepFill(f)) return false;               // 설치 뒤 진입만: entered at or after the install
      if (st.per === "today" && f.exit_time < day0) return false;
      if (coin && coinOf(f.symbol) !== coin) return false;
      if (st.grp !== "all" && !(a && inGroup(a, st.grp))) return false;
      if (st.res === "win" && !winOf(f)) return false;
      if (st.res === "loss" && winOf(f)) return false;
      if (st.res === "liq" && f.exit_reason !== "LIQ") return false;
      return true;
    });
  }
  function render(keep) {
    if (st.err && !st.fills) { put(sum, ui.errorBox(st.err, load)); return; }
    if (!st.fills) return;
    const ix = LK.index();
    const rs = rows();
    const line = fillSum(rs, ix.byId);
    const tag = afterTag();
    if (tag) line.append(" ", tag);
    put(sum, line);
    const now = serverNow();
    pager.set(rs.map((f) => fillRow(f, ix.byId[f.account], {href: ctx.href, now})), keep);
    const hid = !rs.length && afterOn() ? rows(true).length : 0;
    put(gone, hid ? afterEmpty("설치 뒤에 들어간 닫힌 거래가 아직 없습니다", `조건에 맞는 최근 거래 ${fmt.int(hid)}건은 설치 전에 들어간 것이라 '설치 뒤 진입만'에서 숨겼습니다`) : null);
    pager.el.hidden = !!hid;
    const cut = st.fills.length >= 300;
    note.textContent = (st.per === "today" ? "오늘 = 한국 시각 0시부터 (서버 시계). " : "") +
      (afterOn() ? "설치 뒤에 들어간 거래만 (설치 전에 들어가 설치 뒤에 닫힌 거래도 뺌). " : "") +
      (cut ? "서버가 최근 300건까지만 보냅니다. " : "") + "한 줄을 누르면 터미널에서 그 거래. 손익은 나갈 때 수수료·펀딩·슬리피지 뒤입니다.";
  }
  if (coinSeg) coinSeg.set("");
  return {el, load, render, get loaded() { return !!st.fills; }};
}

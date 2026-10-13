// 터미널 bottom table (the rule bot's v4 terminal-table.js, copied and adapted): one head line — the tabs 포지션 n / 체결 /
// 손절 주문, the 묶음 select (후보 by default; 전체 = all 190 accounts), the long / short share bar, the open count and the
// unrealized total in USDT — and a dense table under it.
//   포지션     every open position of the 묶음: 계좌 · 코인 · 방향 · 배수 · 진입가 · 마크 · 미실현 (USDT) · ROE · 청산가 ·
//             손절·잠금 · 진입; the biggest |P&L| first (40 at most). A row picks the position (its coin and its lines on
//             the chart); the coin button picks only the coin.
//   체결       the newest closed trades of the 묶음 (/api/fills): 청산 · 계좌 · 코인 · 방향 · 배수 · 진입 → 청산 · 이유 ·
//             ROE · 손익. A row opens that trade on the chart.
//   손절 주문  the stop, lock and take-profit prices every open position holds, the nearest to the price first (paper:
//             nothing is sent to an exchange).
// Numbers: P&L and ROE at the mark price, before the exit fee (js/poskit.js livePnl); size, margin and the liquidation
// price are "진입 때 기준" (the server's rebuild). While the engine catches up or its record is old, no live P&L,
// ROE or distance is shown (the entry-time ones are, marked so; a lock line then reads "잠금 중", never "닿음"); the same
// when the prices are over a minute old (poskit liveOk). On a phone the rows become small cards (no sideways page
// scroll). The 5 s live tick only changes the numbers in their cells: the rows are built and ordered when the positions,
// the tab or the 묶음 change (and once more when the first prices come), so a focused row or a click is never lost.
// D11: a hidden DeepSeek position or trade is counted in the foot line only. 설치 뒤 진입만 (js/after.js): the positions and
// fills come filtered by terminal.js; the head's 열린 n and 미실현 합계 then carry the 설치 뒤만 chip, the foot says 설치
// 뒤만, and a tab the switch emptied says how many it hid, with the button that turns it off.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as LK from "../lk.js";
import {markOf} from "../live.js";
import {POS_GROUPS, inGroup, livePnl, liveOk, waitKo, gap} from "../poskit.js";
import {countTo, swap} from "../v4kit.js";
import {coinShort, coinOf, reasonKo, lineupOn} from "../labels.js";
import {panel, ratioBar, acctLabel, sideTag, hiddenPos, hiddenFill, usdt, pctOf, ping} from "./terminal-kit.js";
import {afterEmpty, afterTag, keepFill, installMs} from "../after.js";

const MAX = 40;
const NARROW = "(max-width: 899px)";
const narrowNow = () => typeof matchMedia === "function" && matchMedia(NARROW).matches;

/** A small segmented control with the buttons kept (the 포지션 n label changes). */
function tabSeg(options, value, onChange) {
  const btns = new Map();
  const el = h("div", {class: "seg tm-seg", role: "tablist", "aria-label": "아래 표"}, options.map((o) => {
    const b = h("button", {type: "button", role: "tab", "aria-selected": String(o.id === value), onclick: () => { set(o.id); onChange(o.id); }}, o.label);
    btns.set(o.id, b);
    return b;
  }));
  const set = (id) => { for (const [k, b] of btns) b.setAttribute("aria-selected", String(k === id)); };
  el.set = set;
  el.btn = (id) => btns.get(id);
  return el;
}

/** bottomTable(ctx, st, hooks) -> {el, onPositions(doc), onLive(), onFills(rows), setCoin(), setSel(), setGroup()}
 *  hooks: {onPick(id), onCoin(coin), onGroup(id), onTrade({account, coin, at})} */
export function bottomTable(ctx, st, hooks) {
  const T = {tab: ["pos", "fills", "stops"].includes(local.get("tm-tab", "pos")) ? local.get("tm-tab", "pos") : "pos", doc: null, fills: null, fillsAll: null, fillsFailed: false};
  const tabs = tabSeg([{id: "pos", label: "포지션"}, {id: "fills", label: "체결"}, {id: "stops", label: "손절 주문"}], T.tab,
    (id) => { T.tab = id; local.set("tm-tab", id); render(true); });
  const grp = h("select", {class: "select tm-sel", "aria-label": "묶음 고르기", title: "묶음: 후보 · 1/4 · 청산만 · 기본값 · 동전 계좌, 또는 기존 36 · 딥시크 (전체 = 190계좌)"},
    POS_GROUPS.map((g) => h("option", {value: g.id}, g.ko)));
  grp.value = st.grp;
  grp.addEventListener("change", () => hooks.onGroup(grp.value));
  const total = h("b", {class: "num tm-utot"}, "—");
  const ratio = ratioBar([{key: "L", label: "롱", tone: "up"}, {key: "S", label: "숏", tone: "down"}], {label: "열린 포지션 롱·숏 비율", cls: "wide inline"});
  const openN = h("b", {class: "num"}, "—");
  const tbl = h("div", {class: "tm-tw"});
  const foot = h("div", {class: "tm-pf row"});
  const totBox = h("span", {class: "tm-ut", title: "고른 묶음의 미실현 손익 합계 (마크 가격, 나갈 때 수수료 전 · 딥시크 금액 숨김이면 뺌)"}, "미실현 합계 ", total, " USDT");
  const aftSlot = h("span", {class: "tm-aft"});                      // 설치 뒤만: the chip on the head's count and sum
  const el = panel("우리 봇", {cls: "tm-table", lead: [tabs], acts: [grp, ratio, h("span", {class: "tm-ut n"}, "열린 ", openN), totBox, aftSlot]}, tbl, foot);
  const cells = new Map();
  const cellOf = (id) => {
    let c = cells.get(id);
    if (!c) { c = {pnl: h("b", {class: "num"}), roe: h("span", {class: "num"}), mk: h("span", null, "—")}; cells.set(id, c); }
    return c;
  };
  // what the shown rows were built from: the live tick repaints these in place (no rebuild, no new order)
  let shownPos = [], shownStops = [], builtLive = null, builtPriced = 0;

  const acctOf = (p) => LK.index().byId[p.id] || {id: p.id, role: p.role, kind: p.kind, name: p.name, tf: p.tf};
  const coinBtn = (coin) => h("button", {type: "button", class: ["tm-coin", coin === st.coin ? "on" : ""], title: "이 코인 보기",
    onclick: (e) => { if (e && e.stopPropagation) e.stopPropagation(); hooks.onCoin(coin); }}, coinShort(coin));
  const table = (cols, rows) => h("table", {class: "tm-t"}, h("thead", null, h("tr", null, cols.map((c) => h("th", {class: c[1] || "", title: c[2] || null}, c[0])))), h("tbody", null, rows));
  const empty = (t) => h("p", {class: "tm-empty"}, t);
  const allowedNow = () => liveOk(T.doc);
  const stale = () => (T.doc && !T.doc.status && !allowedNow()
    ? h("span", {class: "warn-t"}, T.doc.catching_up ? "엔진이 따라잡는 중: 실시간 손익 감춤 · " : `${waitKo(T.doc) || "엔진 기록이 멈춤"}: 실시간 손익 감춤 · `) : null);
  const posLink = () => h("a", {class: "tm-more", href: "#/positions"}, "포지션 화면 →");

  function inGrp() { return T.doc && !T.doc.status ? (T.doc.positions || []).filter((p) => inGroup(p, st.grp)) : []; }
  /** 설치 뒤 진입만: the open positions of the 묶음 the switch left out (entered before the install) */
  const beforeN = () => (T.doc && T.doc.after ? T.doc.after.before.filter((p) => inGroup(p, st.grp)).length : 0);
  const aftFoot = () => (T.doc && T.doc.after ? "설치 뒤만 · " : "");
  const posGone = (what) => afterEmpty(`설치 뒤에 들어간 ${what} 아직 없습니다`,
    `고른 묶음의 열린 포지션 ${fmt.int(beforeN())}개는 모두 설치 전에 들어간 것이라 '설치 뒤 진입만'에서 숨겼습니다`, {cls: "tm-empty", sm: true});

  // ---------------------------------------------------------------- 포지션
  function posView() {
    if (!T.doc) { put(foot, posLink()); return empty("불러오는 중"); }
    if (T.doc.status) { put(foot, posLink()); return empty("엔진 기록 준비 중 (첫 계산이 끝나면 보입니다)"); }
    const allowed = allowedNow();
    const all = inGrp();
    const shown = all.filter((p) => !hiddenPos(p)), hid = all.length - shown.length;
    const xs = shown.map((p) => ({p, u: allowed ? livePnl(p, markOf(p.coin)) : null}));
    xs.sort((a, b) => (b.u ? Math.abs(b.u.pnl) : -1) - (a.u ? Math.abs(a.u.pnl) : -1) || (b.p.since || 0) - (a.p.since || 0));
    const top = xs.slice(0, MAX);
    shownPos = top.map((x) => x.p);
    builtPriced = xs.filter((x) => x.u).length;
    put(foot, h("span", {class: "muted"}, stale(), aftFoot(), hid ? `딥시크 ${fmt.int(hid)}개 열림 (금액 숨김: 개수만, 합계에서 뺌) · ` : "",
      shown.length > MAX ? `손익 큰 ${fmt.int(MAX)}개만 · 전체 ${fmt.int(shown.length)}개는 ` : ""), posLink());
    if (!top.length) return all.length ? empty("고른 묶음의 열린 포지션은 모두 딥시크 (개수만)") : beforeN() ? posGone("열린 포지션이") : empty("고른 묶음에 열린 포지션이 없습니다");
    for (const x of top) paintCells(x.p, x.u, allowed);
    if (narrowNow()) {
      return h("div", {class: "tm-cards"}, top.map((x) => {
        const p = x.p, c = cellOf(p.id);
        return h("button", {type: "button", class: ["tm-pcard", p.id === st.sel ? "on" : "", p.coin === st.coin ? "here" : ""], onclick: () => hooks.onPick(p.id),
          title: "누르면 차트에 이 포지션의 진입·손절선"},
        h("span", {class: "tm-pc1"}, sideTag(p.side), acctLabel(acctOf(p)), h("b", {class: "tm-pcc"}, coinShort(p.coin)), h("span", {class: "num muted"}, fmt.lev(p.lev))),
        h("span", {class: "tm-pc2"}, h("span", {class: "muted"}, "미실현"), c.pnl, h("span", {class: "muted"}, "USDT"), h("span", {class: "grow"}), h("span", {class: "muted"}, "ROE"), c.roe),
        h("span", {class: "tm-pc3 num muted"}, `진입 ${fmt.price(p.entry)} · `, allowed ? [c.mk, " · "] : null, `청산 ${fmt.price(p.liq)} · ${p.stop_is_lock ? "잠금" : "손절"} ${fmt.price(p.stop)}`));
      }));
    }
    const rows = top.map((x) => {
      const p = x.p, c = cellOf(p.id);
      const tr = h("tr", {class: [p.id === st.sel ? "on" : "", "click"], tabindex: "0", title: "누르면 차트에 이 포지션의 진입·손절선"},
        h("td", {class: "nm"}, acctLabel(acctOf(p))), h("td", null, coinBtn(p.coin)), h("td", null, sideTag(p.side)),
        h("td", {class: "r num xn"}, fmt.lev(p.lev)), h("td", {class: "r num xe"}, fmt.price(p.entry)),
        h("td", {class: "r num muted xm"}, allowed ? c.mk : "—"),
        h("td", {class: "r"}, c.pnl), h("td", {class: "r"}, c.roe), h("td", {class: "r num warn-t"}, fmt.price(p.liq)),
        h("td", {class: ["r", "num", p.stop_is_lock ? "up" : ""]}, p.stop == null ? "—" : `${p.stop_is_lock ? "잠금 " : ""}${fmt.price(p.stop)}`),
        h("td", {class: "r num muted xs"}, fmt.kst(p.since)));
      tr.addEventListener("click", () => hooks.onPick(p.id));
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") hooks.onPick(p.id); });
      return tr;
    });
    return table([["계좌"], ["코인"], ["방향"], ["배수", "r xn"], ["진입가", "r xe"], ["마크", "r xm", "마크 가격 (엔진이 강제청산을 보는 가격)"],
      ["미실현 (USDT)", "r", "마크 가격 기준, 나갈 때 수수료 전"], ["ROE", "r", "미실현 ÷ 증거금"], ["청산가", "r", "진입 때 기준 (펀딩이 쌓이면 조금 달라짐)"],
      ["손절·잠금", "r"], ["진입", "r xs"]], rows);
  }

  // ---------------------------------------------------------------- 체결
  function fillsView() {
    if (T.fills == null) { put(foot, h("a", {class: "tm-more", href: "#/fills"}, "체결 기록 전체 →")); return empty(T.fillsFailed ? "체결 기록을 불러오지 못함 · 잠시 뒤 다시 받습니다" : "불러오는 중"); }
    const ix = LK.index();
    const dsm = T.doc && !T.doc.status ? !!T.doc.ds_money : !!(LK.league() && LK.league().ds_money);
    const mine = T.fills.filter((f) => { const a = ix.byId[f.account]; return a ? inGroup(a, st.grp) : st.grp === "all"; });
    const shown = mine.filter((f) => !hiddenFill(f, ix.byId[f.account], dsm));
    const hid = mine.length - shown.length;
    const rows = shown.slice(0, MAX);
    put(foot, h("span", {class: "muted"}, `${aftFoot()}최근 ${fmt.int(rows.length)}건${hid ? ` · 딥시크 ${fmt.int(hid)}건 (금액 숨김: 건수만)` : ""} · `), h("a", {class: "tm-more", href: "#/fills"}, "체결 기록 전체 →"));
    if (!rows.length) {
      if (hid) return empty("고른 묶음의 최근 체결은 모두 딥시크 (건수만)");
      // 설치 뒤 진입만 emptied it: the server's newest trades of the 묶음 that were entered before the install
      const cut = installMs(T.doc);
      const gone = T.fillsAll && T.fillsAll !== T.fills && cut != null ? T.fillsAll.filter((f) => !keepFill(f, cut)
        && ((a) => (a ? inGroup(a, st.grp) : st.grp === "all"))(ix.byId[f.account])).length : 0;
      return gone ? afterEmpty("설치 뒤에 들어간 닫힌 거래가 아직 없습니다", `고른 묶음의 최근 닫힌 거래 ${fmt.int(gone)}건은 설치 전에 들어간 거래라 숨겼습니다`, {cls: "tm-empty", sm: true})
        : empty("고른 묶음에 닫힌 거래가 아직 없습니다");
    }
    const pick = (f) => hooks.onTrade({account: f.account, coin: coinOf(f.symbol), at: f.entry_time});
    if (narrowNow()) {
      return h("div", {class: "tm-cards"}, rows.map((f) => h("button", {type: "button", class: "tm-pcard", onclick: () => pick(f)},
        h("span", {class: "tm-pc1"}, sideTag(f.side), acctLabel(ix.byId[f.account] || {id: f.account}), h("b", {class: "tm-pcc"}, coinShort(coinOf(f.symbol))),
          h("span", {class: "num muted"}, fmt.lev(f.leverage))),
        h("span", {class: "tm-pc2"}, h("span", {class: f.exit_reason === "LIQ" ? "down" : "muted"}, reasonKo(f.exit_reason)), h("b", {class: ["num", fmt.tone(f.pnl, usdt(f.pnl))]}, usdt(f.pnl)),
          h("span", {class: "muted"}, "USDT"), h("span", {class: "grow"}), h("span", {class: ["num", fmt.tone(f.roe, pctOf(f.roe))]}, pctOf(f.roe))),
        h("span", {class: "tm-pc3 num muted"}, `${fmt.kst(f.exit_time)} · ${fmt.price(f.entry_price)} → ${fmt.price(f.exit_price)}`))));
    }
    return table([["청산"], ["계좌"], ["코인"], ["방향"], ["배수", "r xn"], ["진입 → 청산", "r xe"], ["이유"], ["ROE", "r"], ["손익 (USDT)", "r", "수수료·펀딩 포함"]],
      rows.map((f) => {
        const tr = h("tr", {class: "click", tabindex: "0", title: "누르면 차트에서 이 거래"},
          h("td", {class: "num muted"}, fmt.kst(f.exit_time)), h("td", {class: "nm"}, acctLabel(ix.byId[f.account] || {id: f.account})), h("td", null, coinBtn(coinOf(f.symbol))),
          h("td", null, sideTag(f.side)), h("td", {class: "r num xn"}, fmt.lev(f.leverage)),
          h("td", {class: "r num xe"}, `${fmt.price(f.entry_price)} → ${fmt.price(f.exit_price)}`),
          h("td", {class: f.exit_reason === "LIQ" ? "down" : ""}, reasonKo(f.exit_reason)),
          h("td", {class: ["r", "num", fmt.tone(f.roe, pctOf(f.roe))]}, pctOf(f.roe)), h("td", {class: ["r", "num", fmt.tone(f.pnl, usdt(f.pnl))]}, usdt(f.pnl)));
        tr.addEventListener("click", (e) => { if (!(e && e.target && e.target.closest && e.target.closest("button"))) pick(f); });
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter") pick(f); });
        return tr;
      }));
  }

  // ---------------------------------------------------------------- 손절 주문
  /** one order's distance: from the mark when live numbers are allowed and the coin has a price, else from the entry
   *  (marked "진입 때"); a lock line from the entry has none (it sits past the entry on the profit side by design) */
  function orderDist(x, allowed) {
    const p = x.p;
    const m = allowed ? markOf(p.coin) : null;
    x.m = m;
    x.idle = m == null && x.kind === "lock";
    const ref = m != null ? m : Number(p.entry);
    x.d = x.idle ? null : x.kind === "tp" ? -gap(p.side, ref, p.tp) : gap(p.side, ref, p.stop);
    return x;
  }
  /** every stop / lock / take-profit of the shown positions, the nearest first (lock lines without a distance last) */
  function orderRows() {
    const allowed = allowedNow();
    const out = [];
    for (const p of inGrp()) {
      if (hiddenPos(p)) continue;
      if (p.stop != null) out.push(orderDist({p, kind: p.stop_is_lock ? "lock" : "stop", price: Number(p.stop)}, allowed));
      if (p.tp != null) out.push(orderDist({p, kind: "tp", price: Number(p.tp)}, allowed));
    }
    return out.sort((a, b) => (a.d ?? 9) - (b.d ?? 9));
  }
  function stopsView() {
    if (!T.doc || T.doc.status) { put(foot, posLink()); return empty(T.doc ? "엔진 기록 준비 중" : "불러오는 중"); }
    const allowed = allowedNow();
    const xs = orderRows().slice(0, MAX);
    shownStops = xs;
    const hid = inGrp().filter(hiddenPos).length;
    put(foot, h("span", {class: "muted"}, stale(), "모의 계좌의 손절·잠금·익절 가격 (거래소에 걸린 실제 주문 아님)", hid ? ` · 딥시크 ${fmt.int(hid)}개는 개수만` : ""));
    if (!xs.length) return !inGrp().length && beforeN() ? posGone("포지션의 손절 주문이") : empty("걸린 손절이 없습니다");
    const KO = {stop: "손절", lock: "잠금", tp: "익절"};
    for (const x of xs) { x.dEl = h("b"); x.mEl = h("span"); paintDist(x); }
    if (narrowNow()) {
      return h("div", {class: "tm-cards"}, xs.map((x) => h("button", {type: "button", class: ["tm-pcard", x.p.id === st.sel ? "on" : ""], onclick: () => hooks.onPick(x.p.id)},
        h("span", {class: "tm-pc1"}, sideTag(x.p.side), acctLabel(acctOf(x.p)), h("b", {class: "tm-pcc"}, coinShort(x.p.coin))),
        h("span", {class: "tm-pc2"}, h("span", {class: x.kind === "stop" ? "down" : "up"}, KO[x.kind]), h("b", {class: "num"}, fmt.price(x.price)), h("span", {class: "grow"}),
          h("span", {class: "muted"}, allowed ? "거리" : "진입 때 거리"), x.dEl))));
    }
    return table([["계좌"], ["코인"], ["방향"], ["종류"], ["가격", "r"], [allowed ? "지금" : "진입가", "r"], [allowed ? "거리" : "진입 때 거리", "r", "가격이 이만큼 더 움직이면 닿음"], ["청산가", "r"]],
      xs.map((x) => {
        const tr = h("tr", {class: ["click", x.p.id === st.sel ? "on" : ""], tabindex: "0"},
          h("td", {class: "nm"}, acctLabel(acctOf(x.p))), h("td", null, coinBtn(x.p.coin)), h("td", null, sideTag(x.p.side)),
          h("td", {class: x.kind === "stop" ? "down" : "up"}, x.kind === "lock" ? "잠금 (수익 확정선)" : KO[x.kind]),
          h("td", {class: "r num"}, fmt.price(x.price)), h("td", {class: "r num muted"}, x.mEl),
          h("td", {class: "r"}, x.dEl), h("td", {class: "r num warn-t"}, fmt.price(x.p.liq)));
        tr.addEventListener("click", (e) => { if (!(e && e.target && e.target.closest && e.target.closest("button"))) hooks.onPick(x.p.id); });
        return tr;
      }));
  }

  // ---------------------------------------------------------------- the head and the render
  function paintHead() {
    const all = inGrp();
    put(aftSlot, T.doc && T.doc.after ? afterTag(T.doc) : null);  // 설치 뒤 진입만: the count and the sum say so
    const L = all.filter((p) => Number(p.side) > 0).length, S = all.length - L;
    ratio.set({L, S}, (n, sh) => fmt.pct(sh * 100, false, 1));
    openN.textContent = T.doc && !T.doc.status ? fmt.int(all.length) : "—";
    tabs.btn("pos").textContent = T.doc && !T.doc.status ? `포지션 ${fmt.int(all.length)}` : "포지션";
    if (!allowedNow()) {
      countTo(total, null);
      totBox.title = T.doc && T.doc.catching_up ? "엔진이 따라잡는 중: 지금 가격으로 계산하지 않습니다" : `${waitKo(T.doc) || "엔진 기록이 멈춤"}: 실시간 손익을 감춥니다`;
      return;
    }
    let tot = 0, known = 0;
    for (const p of all) { const u = hiddenPos(p) ? null : livePnl(p, markOf(p.coin)); if (u) { tot += u.pnl; known += 1; } }
    countTo(total, known ? tot : null, {format: (v) => usdt(v), tone: true});
    totBox.title = "고른 묶음의 미실현 손익 합계 (마크 가격, 나갈 때 수수료 전 · 딥시크 금액 숨김이면 뺌)";
  }
  /** a position row's live cells: 미실현, ROE and the mark */
  function paintCells(p, u, allowed) {
    const c = cellOf(p.id);
    countTo(c.pnl, u ? u.pnl : null, {format: (v) => usdt(v), tone: true});
    countTo(c.roe, u && u.roe != null ? u.roe : null, {format: (v) => pctOf(v, 1), tone: true});
    const m = allowed ? markOf(p.coin) : null;
    c.mk.textContent = narrowNow() ? `마크 ${fmt.price(m)}` : fmt.price(m);
  }
  /** an order row's live cells: the price it is measured from and the distance (a lock line from the entry: 잠금 중) */
  function paintDist(x) {
    const near = x.d != null && x.d < 0.005;
    x.dEl.className = ["num", near ? "down" : "", x.idle ? "up" : ""].filter(Boolean).join(" ");
    x.dEl.textContent = x.idle ? "잠금 중" : x.d == null ? "—" : fmt.pct(x.d * 100, false, 2);
    x.dEl.title = x.idle ? "진입가에서 재면 잠금선은 늘 수익 쪽에 있어 거리가 없습니다 (닿으면 수익으로 끝남)" : "";
    x.mEl.textContent = fmt.price(x.m != null ? x.m : x.p.entry);
  }
  /** the 5 s tick: numbers only, in the cells already on the page */
  function liveOnly() {
    const allowed = allowedNow();
    if (T.tab === "pos") {
      for (const p of shownPos) paintCells(p, allowed && !hiddenPos(p) ? livePnl(p, markOf(p.coin)) : null, allowed);
    } else if (T.tab === "stops") {
      for (const x of shownStops) { orderDist(x, allowed); paintDist(x); }
    }
  }
  function render(user) {
    grp.title = lineupOn() ? `묶음: 계좌 종류별, 또는 기존 36 · 딥시크 (전체 = ${LK.allAccountsKo()})` : "묶음: 후보 · 1/4 · 청산만 · 기본값 · 동전 계좌, 또는 기존 36 · 딥시크 (전체 = 190계좌)";
    paintHead();
    builtLive = allowedNow();
    const body = T.tab === "fills" ? fillsView() : T.tab === "stops" ? stopsView() : posView();
    tbl.replaceChildren(body);
    if (user) swap(tbl);
  }
  /** rebuild on a live tick only when the rows were built without what the tick brings: live numbers turned on or off,
   *  or the first prices of the shown positions (the order is then by |P&L| once) */
  function needRebuild() {
    if (T.tab === "fills" || !T.doc || T.doc.status) return false;
    const allowed = allowedNow();
    if (allowed !== builtLive) return true;
    if (T.tab !== "pos" || !allowed) return false;
    let n = 0;
    for (const p of inGrp()) if (!hiddenPos(p) && livePnl(p, markOf(p.coin))) n += 1;
    return n > builtPriced;
  }
  if (typeof matchMedia === "function") {
    const mq = matchMedia(NARROW);
    const re = () => { if (ctx.alive()) render(false); };
    if (mq.addEventListener) { mq.addEventListener("change", re); ctx.signal && ctx.signal.addEventListener && ctx.signal.addEventListener("abort", () => mq.removeEventListener("change", re)); }
  }
  render(false);
  return {
    el,
    onPositions(d) { T.doc = d; render(false); },
    onLive() { if (needRebuild()) render(false); else { paintHead(); liveOnly(); } },
    /** rows: what the 체결 tab shows (filtered by terminal.js); all: the server's rows (how many the switch hid) */
    onFills(rows, all) { if (rows == null) { T.fillsFailed = true; } else { const had = T.fills; T.fills = rows; T.fillsAll = all || rows; T.fillsFailed = false; if (had && rows.length && had[0] !== rows[0]) ping(el); } if (T.tab === "fills" || !T.fills) render(false); },
    setCoin() { render(false); },
    setSel() { render(false); },
    setGroup() { grp.value = st.grp; render(false); },
    /** for tests */
    tab: (id) => { T.tab = id; tabs.set(id); render(false); },
  };
}

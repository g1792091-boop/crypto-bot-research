// 터미널 bottom: our open positions as a dense table (term v2, owners 10/06: HelloQuant's positions bar). One head line:
// the tabs 포지션 n / 체결 / 손절 주문, the ALL / group filter, the long / short share bar with its %, the open count and
// the unrealized total. Live numbers roll to a real new mark (motion.countTo); the bar's widths move when the board
// really changed. 체결 = /api/trades (the newest 60, again after a stream `trades` event, debounced). 손절 주문 = the stops
// and locks every position holds, nearest first (paper: nothing is sent).
// HONESTY: money per account only for 기존 36, 5분봉 and the extra accounts (MONEY_G); DeepSeek and the coin flips are
// counted in the foot line (their money is on their own group screens).
import {h, put, ui, fmt, store, motion, local} from "../core/pb.js";
import {normPos} from "./positions-kit.js";
import {panel, ratioBar} from "./terminal-kit.js";

const MAX = 40;
export const MONEY_G = new Set(["core", "m5", "extra"]);
/** each tab's own note (the ⓘ by the tabs) */
const TAB_NOTE = {
  pos: `열린 포지션 · 미실현: ${ui.ASSUME_OPEN_KO} · 기존 36 · 5분봉 · 추가 계좌만 (딥시크·동전 봇은 건수만)`,
  fills: `닫힌 거래 · 손익: ${ui.ASSUME_KO} · 딥시크·동전 봇 빼고`,
  stops: "모의 계좌의 손절·잠금 가격 (거래소에 걸린 실제 주문 아님) · 지금 가격에서 가까운 순",
};

/** bottomTable(ctx, st, onPick) -> {el, setSym, onBoard, onTicker, onTrades} */
export function bottomTable(ctx, st, onPick) {
  const t = {tab: local.get("term-tab", "pos"), g: local.get("term-tg", ""), board: null, trades: null, busy: false};
  if (t.g && !MONEY_G.has(t.g)) t.g = "";
  const tabs = ui.seg([{id: "pos", label: "포지션"}, {id: "fills", label: "체결"}, {id: "stops", label: "손절 주문"}], t.tab,
    (id) => { t.tab = id; local.set("term-tab", id); render(true); }, {label: "아래 표"});
  const posBtn = tabs.querySelector('[data-id="pos"]');
  const grp = h("select", {class: "select term-sel", "aria-label": "묶음 고르기", title: "ALL = 기존 36 · 5분봉 · 추가 계좌 (딥시크·동전 봇은 건수만)"},
    h("option", {value: ""}, "ALL"), fmt.GROUPS.filter((g) => MONEY_G.has(g.id)).map((g) => h("option", {value: g.id}, g.ko)));
  grp.value = t.g;
  grp.addEventListener("change", () => { t.g = grp.value; local.set("term-tg", t.g); render(true); });
  const total = h("b", {class: "num term-utot"}, "—");
  const ratio = ratioBar([{key: "L", label: "롱", tone: "up"}, {key: "S", label: "숏", tone: "down"}], {label: "열린 포지션 롱·숏 비율", cls: "wide inline"});
  const openN = h("b", {class: "num"}, "—");
  const tbl = h("div", {class: "term-tw"});
  const foot = h("div", {class: "term-pf row"});
  // the money caption per tab: the ⓘ by the tabs (its words follow the tab) and the terminal's one footer line (owners
  // 10/06 ~14:00: not under the table as well)
  const el = panel("우리 봇", {cls: "term-table", lead: [tabs], info: TAB_NOTE.pos,
    acts: [grp, ratio, h("span", {class: "term-ut n"}, "열린 ", openN), h("span", {class: "term-ut"}, "미실현 합계 ", total, " USDT")]}, tbl, foot);
  const cells = new Map();          // account id -> {pnl, roe} elements (reused so numbers roll)

  const money = (a) => MONEY_G.has(fmt.groupOf(a));
  const inG = (a) => money(a) && (!t.g || fmt.groupOf(a) === t.g);
  const open = () => (t.board ? t.board.accounts.filter((a) => a.position && inG(a)).map((a) => ({a, p: normPos(a.position)})) : []);
  const pnlOf = (x) => { const m = store.mark(x.p.symbol); return m ? x.p.side * x.p.qty * (m - x.p.entry) : null; };
  const nameCell = (a, id) => h("td", {class: "nm"}, h("a", {href: ctx.href("account", id), title: id}, h("i", {class: ["term-gsw", a ? fmt.groupOf(a) : ""], "aria-hidden": "true"}),
    a ? ui.acctLabel(a) : fmt.idName(id)));
  const coinCell = (sym) => h("td", null, h("button", {type: "button", class: ["term-coin", sym === st.sym ? "on" : ""], onclick: () => onPick(sym), title: "이 코인 보기"}, fmt.coin(sym)));
  const table = (cols, rows) => h("table", {class: "term-t"}, h("thead", null, h("tr", null, cols.map((c) => h("th", {class: c[1] || ""}, c[0])))), h("tbody", null, rows));
  const counted = () => {
    if (!t.board) return "";
    let ds = 0, coin = 0;
    for (const a of t.board.accounts) { if (!a.position) continue; const g = fmt.groupOf(a); if (g === "ds") ds++; else if (g === "coin") coin++; }
    return ds || coin ? `딥시크 ${fmt.int(ds)} · 동전 봇 ${fmt.int(coin)}개 열림 (건수만) · ` : "";
  };

  function posTable() {
    const all = open();
    const xs = all.sort((x, y) => Math.abs(pnlOf(y) ?? 0) - Math.abs(pnlOf(x) ?? 0)).slice(0, MAX);
    const rows = xs.map((x) => {
      const id = x.a.account_id, m = store.mark(x.p.symbol), u = pnlOf(x);
      let c = cells.get(id);
      if (!c) { c = {pnl: h("b", {class: "num"}), roe: h("span", {class: "num"})}; cells.set(id, c); }
      motion.countTo(c.pnl, u, {dec: 2, sign: true, tone: true, glow: true});
      motion.countTo(c.roe, u != null && x.p.margin ? u / x.p.margin : null, {format: "pct", dec: 1, tone: true});
      const lock = x.p.lock_roe != null && !fmt.ownExits(x.a);
      return h("tr", {class: x.p.symbol === st.sym ? "on" : ""}, nameCell(x.a, id), coinCell(x.p.symbol), h("td", null, ui.sideTag(x.p.side)),
        h("td", {class: "r num xn"}, fmt.lev(x.p.leverage)), h("td", {class: "r num xe"}, fmt.price(x.p.entry)), h("td", {class: "r num muted xm"}, fmt.price(m)),
        h("td", {class: "r"}, c.pnl), h("td", {class: "r"}, c.roe), h("td", {class: "r num warn-t"}, fmt.price(x.p.liq)),
        h("td", {class: ["r", "num", lock ? "up" : ""]}, lock ? `잠금 ${fmt.price(x.p.stop)}` : fmt.price(x.p.stop)),
        h("td", {class: "r num muted xs"}, x.p.entry_time ? fmt.kst(x.p.entry_time) : "—"));
    });
    const n = all.length;
    put(foot, h("span", {class: "muted"}, counted(), n > MAX ? `손익 큰 ${fmt.int(MAX)}개만 · 전체 ${fmt.int(n)}개는 ` : "",
      h("a", {href: ctx.href("positions")}, "포지션 화면 →")));
    return rows.length ? table([["계좌"], ["코인"], ["방향"], ["배수", "r xn"], ["진입가", "r xe"], ["마크", "r xm"], ["미실현 (USDT)", "r"], ["ROE", "r"], ["청산가", "r"],
      ["손절·잠금", "r"], ["진입", "r xs"]], rows) : ui.empty("열린 포지션이 없습니다");
  }
  function fillsTable() {
    if (!t.trades) { loadTrades(); return motion.shimmer(3); }
    const byId = new Map(((t.board && t.board.accounts) || []).map((a) => [a.account_id, a]));
    const gOf = (x) => (byId.get(x.account_id) ? fmt.groupOf(byId.get(x.account_id)) : fmt.SERVER_GROUP[x.group]);
    const rows = t.trades.filter((x) => MONEY_G.has(gOf(x)) && (!t.g || gOf(x) === t.g)).slice(0, MAX).map((x) =>
      h("tr", null, h("td", {class: "num muted"}, fmt.kst(x.exit_time)), nameCell(byId.get(x.account_id), x.account_id), coinCell(x.symbol),
        h("td", null, ui.sideTag(x.side)), h("td", {class: "r num"}, fmt.lev(x.leverage)),
        h("td", {class: "r num"}, `${fmt.price(x.entry_price)} → ${fmt.price(x.exit_price)}`),
        h("td", {class: x.exit_reason === "LIQ" ? "down" : ""}, fmt.reasonKo(x.exit_reason)),
        h("td", {class: ["r", "num", fmt.tone(x.roe)]}, fmt.pct(x.roe, 1)), h("td", {class: ["r", "num", fmt.tone(x.pnl)]}, fmt.money(x.pnl, true))));
    put(foot, h("span", {class: "muted"}, `최근 ${fmt.int(rows.length)}건 (딥시크·동전 봇 빼고) · `, h("a", {href: ctx.href("positions")}, "체결 기록 전체 →")));
    return rows.length ? table([["청산"], ["계좌"], ["코인"], ["방향"], ["배수", "r"], ["진입 → 청산", "r"], ["이유"], ["ROE", "r"], ["손익 (USDT)", "r"]], rows)
      : ui.empty("체결이 아직 없습니다");
  }
  function stopsTable() {
    const xs = open().filter((x) => x.p.stop).map((x) => {
      const m = store.mark(x.p.symbol);
      return {...x, m, d: m ? Math.abs(m - x.p.stop) / m : null};
    }).sort((x, y) => (x.d ?? 9) - (y.d ?? 9)).slice(0, MAX);
    const rows = xs.map((x) => {
      const lock = x.p.lock_roe != null && !fmt.ownExits(x.a);
      return h("tr", null, nameCell(x.a, x.a.account_id), coinCell(x.p.symbol), h("td", null, ui.sideTag(x.p.side)),
        h("td", null, fmt.ownExits(x.a) ? "스윙 저점 손절" : lock ? h("span", {class: "up"}, `잠금 +${fmt.num(x.p.lock_roe * 100, 0)}%`) : "손절"),
        h("td", {class: "r num"}, fmt.price(x.p.stop)), h("td", {class: "r num muted"}, fmt.price(x.m)),
        h("td", {class: ["r", "num", x.d != null && x.d < 0.005 ? "down" : ""]}, x.d == null ? "—" : fmt.pct(x.d, 2, false)),
        h("td", {class: "r num warn-t"}, fmt.price(x.p.liq)));
    });
    put(foot, h("span", {class: "muted"}, "모의 계좌의 손절·잠금 가격 (실제 주문 아님)"));
    return rows.length ? table([["계좌"], ["코인"], ["방향"], ["종류"], ["가격", "r"], ["지금", "r"], ["거리", "r"], ["청산가", "r"]], rows) : ui.empty("걸린 손절이 없습니다");
  }
  function render(user) {
    el.tip.set(TAB_NOTE[t.tab] || TAB_NOTE.pos);
    const b = t.board;
    if (b) {
      let L = 0, S = 0, tot = 0, known = 0;
      for (const a of b.accounts) {
        if (a.bust || !a.position || !inG(a)) continue;
        if (Number(a.position.side) > 0) L++; else S++;
        const u = pnlOf({p: normPos(a.position)});
        if (u != null) { tot += u; known++; }
      }
      ratio.set({L, S}, (n, sh) => fmt.pct(sh, 1, false));
      openN.textContent = fmt.int(L + S);
      if (posBtn) posBtn.textContent = `포지션 ${fmt.int(L + S)}`;
      motion.countTo(total, known ? tot : null, {dec: 2, sign: true, tone: true, glow: true});
    }
    const body = t.tab === "fills" ? fillsTable() : t.tab === "stops" ? stopsTable() : posTable();
    tbl.replaceChildren(body);
    if (user) motion.swap(tbl);
  }
  async function loadTrades() {
    if (t.busy) return;
    t.busy = true;
    try { t.trades = await ctx.api("/api/trades?limit=60"); } catch (e) { if (!t.trades) t.trades = []; }
    finally { t.busy = false; }
    if (ctx.alive() && t.tab === "fills") render(false);
  }
  let trT = null;
  ctx.track(() => clearTimeout(trT));
  return {
    el,
    setSym() { render(false); },
    onBoard(b) { t.board = b; render(false); },
    onTicker() { render(false); },
    // a new closed trade: the 체결 tab asks again (once per burst); other tabs ask when they are opened next
    onTrades() {
      clearTimeout(trT);
      trT = setTimeout(() => { if (!ctx.alive()) return; if (t.tab === "fills") loadTrades(); else t.trades = null; }, 1500);
    },
  };
}

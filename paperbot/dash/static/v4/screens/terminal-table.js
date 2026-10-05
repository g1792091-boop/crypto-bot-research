// 터미널 bottom: every open position as a dense table (tabs 포지션 / 체결 / 손절 주문, a group filter), the unrealized
// total and the long / short / flat bar of all accounts. Live numbers roll to a real new mark (motion.countTo); the
// bar's widths move when the board really changed. 체결 = /api/trades (the newest 60, again after a stream `trades`
// event, debounced). 손절 주문 = the stops and locks every position holds, nearest first (paper: nothing is sent).
import {h, put, ui, fmt, store, motion, local} from "../core/pb.js";
import {normPos} from "./positions-kit.js";
import {panel, ratioBar} from "./terminal-kit.js";

const MAX = 40;

/** bottomTable(ctx, st, onPick) -> {el, setSym, onBoard, onTicker, onTrades} */
export function bottomTable(ctx, st, onPick) {
  const t = {tab: local.get("term-tab", "pos"), g: local.get("term-tg", ""), board: null, trades: null, busy: false};
  const tabs = ui.seg([{id: "pos", label: "포지션"}, {id: "fills", label: "체결"}, {id: "stops", label: "손절 주문"}], t.tab,
    (id) => { t.tab = id; local.set("term-tab", id); render(true); }, {label: "아래 표"});
  const grp = h("select", {class: "select term-sel", "aria-label": "묶음"}, h("option", {value: ""}, "모든 묶음"), fmt.GROUPS.map((g) => h("option", {value: g.id}, g.ko)));
  grp.value = t.g;
  grp.addEventListener("change", () => { t.g = grp.value; local.set("term-tg", t.g); render(true); });
  const total = h("b", {class: "num term-utot"}, "—");
  const ratio = ratioBar([{key: "L", label: "롱", tone: "up"}, {key: "S", label: "숏", tone: "down"}, {key: "F", label: "대기", tone: "flat"}],
    {label: "모든 계좌 롱·숏·대기", cls: "wide"});
  const tbl = h("div", {class: "term-tw"});
  const foot = h("div", {class: "term-pf row"});
  const el = panel("모든 계좌", {cls: "term-table", acts: [ratio, h("span", {class: "term-ut"}, "미실현 합계 ", total, " USDT"), grp]}, tabs, tbl, foot);
  const cells = new Map();          // account id -> {pnl, roe} elements (reused so numbers roll)

  const inG = (a) => !t.g || fmt.groupOf(a) === t.g;
  const open = () => (t.board ? t.board.accounts.filter((a) => a.position && inG(a)).map((a) => ({a, p: normPos(a.position)})) : []);
  const pnlOf = (x) => { const m = store.mark(x.p.symbol); return m ? x.p.side * x.p.qty * (m - x.p.entry) : null; };
  const nameCell = (a, id) => h("td", {class: "nm"}, h("a", {href: ctx.href("account", id), title: id}, h("i", {class: ["term-gsw", a ? fmt.groupOf(a) : ""], "aria-hidden": "true"}),
    a ? ui.acctLabel(a) : fmt.idName(id)));
  const coinCell = (sym) => h("td", null, h("button", {type: "button", class: ["term-coin", sym === st.sym ? "on" : ""], onclick: () => onPick(sym), title: "이 코인 보기"}, fmt.coin(sym)));
  const table = (cols, rows) => h("table", {class: "term-t"}, h("thead", null, h("tr", null, cols.map((c) => h("th", {class: c[1] || ""}, c[0])))), h("tbody", null, rows));

  function posTable() {
    const xs = open().sort((x, y) => Math.abs(pnlOf(y) ?? 0) - Math.abs(pnlOf(x) ?? 0)).slice(0, MAX);
    const rows = xs.map((x) => {
      const id = x.a.account_id, m = store.mark(x.p.symbol), u = pnlOf(x);
      let c = cells.get(id);
      if (!c) { c = {pnl: h("b", {class: "num"}), roe: h("span", {class: "num"})}; cells.set(id, c); }
      motion.countTo(c.pnl, u, {dec: 2, sign: true, tone: true, glow: true});
      motion.countTo(c.roe, u != null && x.p.margin ? u / x.p.margin : null, {format: "pct", dec: 1, tone: true});
      const lock = x.p.lock_roe != null && !fmt.ownExits(x.a);
      return h("tr", {class: x.p.symbol === st.sym ? "on" : ""}, nameCell(x.a, id), coinCell(x.p.symbol), h("td", null, ui.sideTag(x.p.side)),
        h("td", {class: "r num xn"}, fmt.lev(x.p.leverage)), h("td", {class: "r num xe"}, fmt.price(x.p.entry)), h("td", {class: "r num muted xm"}, fmt.price(m)),
        h("td", {class: "r"}, c.pnl), h("td", {class: "r"}, c.roe), h("td", {class: "r num down-t"}, fmt.price(x.p.liq)),
        h("td", {class: ["r", "num", lock ? "up" : ""]}, lock ? `잠금 ${fmt.price(x.p.stop)}` : fmt.price(x.p.stop)),
        h("td", {class: "r num muted xs"}, x.p.entry_time ? fmt.kst(x.p.entry_time) : "—"));
    });
    const n = open().length;
    put(foot, ui.assume("open"), h("span", {class: "muted"}, n > MAX ? `손익 큰 ${fmt.int(MAX)}개만 · 전체 ${fmt.int(n)}개는 ` : `${fmt.int(n)}개 · `,
      h("a", {href: ctx.href("positions")}, "포지션 화면 →")));
    return rows.length ? table([["계좌"], ["코인"], ["방향"], ["배수", "r xn"], ["진입가", "r xe"], ["마크", "r xm"], ["미실현 (USDT)", "r"], ["ROE", "r"], ["청산가", "r"],
      ["손절·잠금", "r"], ["진입", "r xs"]], rows) : ui.empty("열린 포지션이 없습니다");
  }
  function fillsTable() {
    if (!t.trades) { loadTrades(); return motion.shimmer(3); }
    const byId = new Map(((t.board && t.board.accounts) || []).map((a) => [a.account_id, a]));
    const rows = t.trades.filter((x) => !t.g || (byId.get(x.account_id) ? fmt.groupOf(byId.get(x.account_id)) : fmt.SERVER_GROUP[x.group]) === t.g).slice(0, MAX).map((x) =>
      h("tr", null, h("td", {class: "num muted"}, fmt.kst(x.exit_time)), nameCell(byId.get(x.account_id), x.account_id), coinCell(x.symbol),
        h("td", null, ui.sideTag(x.side)), h("td", {class: "r num"}, fmt.lev(x.leverage)),
        h("td", {class: "r num"}, `${fmt.price(x.entry_price)} → ${fmt.price(x.exit_price)}`),
        h("td", {class: x.exit_reason === "LIQ" ? "down" : ""}, fmt.reasonKo(x.exit_reason)),
        h("td", {class: ["r", "num", fmt.tone(x.roe)]}, fmt.pct(x.roe, 1)), h("td", {class: ["r", "num", fmt.tone(x.pnl)]}, fmt.money(x.pnl, true))));
    put(foot, ui.assume("closed"), h("span", {class: "muted"}, `최근 ${fmt.int(rows.length)}건 · `, h("a", {href: ctx.href("positions")}, "체결 기록 전체 →")));
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
        h("td", {class: "r num down-t"}, fmt.price(x.p.liq)));
    });
    put(foot, h("span", {class: "muted"}, "모의 계좌의 손절·잠금 가격 (실제 주문 아님) · 지금 가격에서 가까운 순"));
    return rows.length ? table([["계좌"], ["코인"], ["방향"], ["종류"], ["가격", "r"], ["지금", "r"], ["거리", "r"], ["청산가", "r"]], rows) : ui.empty("걸린 손절이 없습니다");
  }
  function render(user) {
    const b = t.board;
    if (b) {
      let L = 0, S = 0, F = 0, tot = 0, known = 0;
      for (const a of b.accounts) {
        if (a.bust) continue;
        if (!a.position) { F++; continue; }
        if (Number(a.position.side) > 0) L++; else S++;
        if (!inG(a)) continue;
        const u = pnlOf({p: normPos(a.position)});
        if (u != null) { tot += u; known++; }
      }
      ratio.set({L, S, F}, (n) => fmt.int(n));
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

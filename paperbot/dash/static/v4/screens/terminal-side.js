// 터미널 right column (term v2, owners 10/06: HelloQuant's right column without the order form):
//   - 이 코인 포지션: this coin's open positions of OUR named accounts (기존 36, 5분봉, 추가: live ROE at the mark price;
//     the numbers roll to a real new mark). Owners 10/06 ~14:00: the strategy's full Korean name (two lines when it
//     needs them, the timeframe chip kept); the liquidation and entry prices in each row's tooltip. DeepSeek and the
//     coin flips are counted only (their money is on their own group screens). Paper: 주문 버튼 없음.
//   - 수익 차트 (기존 36): terminal-pnl.js (the closed trades of each hour, 승·패, 최대 낙폭, 오늘 수익, 수익 캘린더).
// HONESTY: realized money of closed trades only (the open positions' P&L is in the table below), the 36 only, 참고 (a
// running record, not a verdict); a day without a record is 기록 없음, never a zero; nothing is drawn before the first
// real day. The captions are said once (owners 10/06 ~14:00): an ⓘ in each head with that panel's exact note, the
// terminal's one footer line.
import {h, put, ui, fmt, store, motion} from "../core/pb.js";
import {normPos} from "./positions-kit.js";
import {panel} from "./terminal-kit.js";
import {failNote} from "./terminal-state.js";
import {MONEY_G} from "./terminal-table.js";       // the groups whose money is shown per account (DeepSeek / coin flips: counts only)

// ---------------------------------------------------------------- this coin's positions
/** coinPositions(ctx, st) -> {el, setSym, onBoard, onTicker} */
export function coinPositions(ctx, st) {
  const list = h("div", {class: "term-cp", role: "list"});
  const other = h("p", {class: "term-cpo muted", hidden: true});
  // (owners 10/06 ~14:00) the money caption is the ⓘ and the terminal's one footer line; the strategy name gets the
  // room (two lines if needed, the timeframe chip kept): 청산가 moved into each row's tooltip
  const el = panel("이 코인 포지션", {cls: "term-mine", scroll: true,
    info: `우리 계좌(기존 36 · 5분봉 · 추가)의 이 코인 열린 포지션 · ROE: ${ui.ASSUME_OPEN_KO} · 청산가·진입가는 줄에 마우스를 올리면 · 딥시크·동전 봇은 건수만`}, list, other);
  let board = null, failed = false;
  const rows = new Map();          // account id -> {key, node, roe}
  function render() {
    const mk = store.mark(st.sym);
    const all = board ? board.accounts.filter((a) => a.position && a.position.symbol === st.sym) : [];
    const xs = all.filter((a) => MONEY_G.has(fmt.groupOf(a))).map((a) => ({a, p: normPos(a.position)}));
    xs.sort((x, y) => (y.p.entry_time || 0) - (x.p.entry_time || 0));
    const L = xs.filter((x) => x.p.side > 0).length;
    el.sub.textContent = board ? `${fmt.coin(st.sym)} · ${fmt.int(xs.length)}개 · 롱 ${fmt.int(L)} · 숏 ${fmt.int(xs.length - L)}` : "";
    const nDs = all.filter((a) => fmt.groupOf(a) === "ds").length, nCoin = all.filter((a) => fmt.groupOf(a) === "coin").length;
    other.hidden = !(nDs || nCoin);
    other.textContent = `딥시크 ${fmt.int(nDs)} · 동전 봇 ${fmt.int(nCoin)}개도 열림 (건수만)`;
    const nodes = xs.slice(0, 20).map((x) => {
      const id = x.a.account_id, key = `${st.sym}|${x.p.entry_time}|${x.p.liq}`;
      let r = rows.get(id);
      if (!r || r.key !== key) {
        const roe = h("b", {class: "num term-roe"}, "—");
        const node = h("a", {class: "term-cr", role: "listitem", href: ctx.href("account", id),
          title: `${id} · 진입 ${fmt.price(x.p.entry)} · ${fmt.lev(x.p.leverage)} · 청산가 ${fmt.price(x.p.liq)}`},
          ui.sideTag(x.p.side), h("span", {class: "term-fn term-cfn"}, h("i", {class: ["term-gsw", fmt.groupOf(x.a)], "aria-hidden": "true"}), ui.acctLabel(x.a)),
          h("span", {class: "muted num"}, fmt.lev(x.p.leverage)), roe);
        r = {key, node, roe};
        rows.set(id, r);
      }
      const u = mk && x.p.margin ? (x.p.side * x.p.qty * (mk - x.p.entry)) / x.p.margin : null;
      motion.countTo(r.roe, u, {format: "pct", dec: 1, tone: true, glow: true});
      return r.node;
    });
    if (!nodes.length) put(list, board ? ui.empty(`${fmt.coin(st.sym)}에 열린 포지션이 없습니다`)
      : failed ? failNote("이 코인의 포지션 (순위 자료)", {retry: () => { store.refresh("board").catch(() => {}); }}) : ui.empty("불러오는 중"));
    else list.replaceChildren(h("div", {class: "term-cr hd", "aria-hidden": "true"}, h("span", null, "방향"), h("span", null, "계좌"), h("span", null, "배수"),
      h("span", null, "ROE")), ...nodes);
  }
  return {el, setSym() { rows.clear(); render(); }, onBoard(b) { board = b; failed = false; render(); },
    /** The board could not be read: the list says so (not "no open position") while there is no board to show. */
    onBoardFailed(f) { if (failed === f) return; failed = f; if (!board) render(); }, onTicker: render};
}

// ---------------------------------------------------------------- 수익 (기존 36): chart, today, calendar
// moved to terminal-pnl.js (term-plus: hourly points, 승·패, 최대 낙폭, honest loading / failed states); the terminal imports it from here as before
export {pnlPanel} from "./terminal-pnl.js";

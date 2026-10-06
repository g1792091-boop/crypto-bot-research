// 순위표 '표' view (fill-people): v3's dense sortable table, 50 rows per page. Columns: 순위, 계좌, 잔고, 수익률, 거래,
// 승률 (n승 n패), 최대 낙폭, 상태 (the open position with its live ROE, home-shared posChip / paintRoe), 동전 봇 대비 (참고).
// HONESTY: in a mixed list (전체) a DeepSeek or coin-flip row is COUNTED ONLY (거래 · 승패 · 상태 without money, D10/D11);
// inside its own group (딥시크 / 동전 봇) the row shows what the card list there shows. 동전 봇 대비 is a neutral glyph (참고).
import {h, put, fmt, derive, fav} from "../core/pb.js";
import {posChip, refTag, groupKo} from "./home-shared.js";

export const PAGE = 50;
const COLS = [
  {id: "rk", label: "순위", key: (a) => (a._rk == null ? 1e9 + (a._at || 0) : a._rk)},
  {id: "name", label: "계좌", l: true, key: (a) => fmt.acctName(a)},
  {id: "wallet", label: "잔고", key: (a, m) => (m(a) ? -(a.wallet ?? 0) : 1e12)},
  {id: "ret", label: "수익률", key: (a, m) => (m(a) ? -a.ret : 1e12)},
  {id: "trades", label: "거래", key: (a) => -(a.trades || 0)},
  {id: "win", label: "승률", key: (a) => -(a.win_rate ?? -1)},
  {id: "dd", label: "최대 낙폭", key: (a, m) => (m(a) ? a.max_drawdown ?? 0 : 1e12)},
  {id: "pos", label: "상태", l: true, key: (a) => (a.position ? 0 : a.bust ? 2 : 1)},
  {id: "vs", label: "동전 봇 대비", key: () => 0, nosort: true},
];

/** Whether a row may show money in this view: never a DeepSeek / coin-flip row outside its own group. */
export function moneyOk(a, group) {
  const g = fmt.groupOf(a);
  if (g === "ds") return group === "ds";
  if (g === "coin") return group === "coin";
  return true;
}

/** Sort rows by a column (stable; ties by return). dir 1 = the column's natural order, -1 reversed. */
export function sortRows(rows, col, dir, group) {
  const c = COLS.find((x) => x.id === col) || COLS[0];
  const m = (a) => moneyOk(a, group);
  return [...rows].sort((x, y) => {
    const p = c.key(x, m), q = c.key(y, m);
    const r = p < q ? -1 : p > q ? 1 : 0;
    return r ? r * dir : (x._rk ?? 1e9 + (x._at || 0)) - (y._rk ?? 1e9 + (y._at || 0));
  });
}

/** boardTable(ctx) -> {el, set(board, gs, group)}: the dense table with its own pager and search. */
export function boardTable(ctx, o = {}) {
  const st = {rows: [], group: "core", gs: null, col: "rk", dir: 1, page: 0, q: ""};
  const search = h("input", {class: "search", type: "search", placeholder: "이름·코드 찾기", "aria-label": "표에서 계좌 찾기", autocomplete: "off"});
  const thead = h("thead");
  // until the first board: 불러오는 중 (the empty words below come only from a real answer)
  const tbody = h("tbody", null, h("tr", null, h("td", {colspan: String(COLS.length), class: "l muted", "aria-busy": "true"}, "불러오는 중")));
  const info = h("span", {class: "pinfo"});
  const prev = h("button", {class: "btn-line", type: "button"}, "이전");
  const next = h("button", {class: "btn-line", type: "button"}, "다음");
  const bar = h("div", {class: "pager"}, prev, info, next);
  const note = h("p", {class: "assume home-vsfoot"});
  const el = h("div", {class: "stack tight bt-wrap"}, search,
    h("div", {class: "tbl-wrap bt-scroll"}, h("table", {class: "tbl bt-tbl"}, thead, tbody)), bar, note);
  search.addEventListener("input", () => { st.q = search.value.trim().toLowerCase(); st.page = 0; render(); });
  prev.addEventListener("click", () => { st.page--; render(); });
  next.addEventListener("click", () => { st.page++; render(); });

  function head() {
    put(thead, h("tr", null, COLS.map((c) => {
      const on = st.col === c.id;
      const th = h("th", {class: [c.l ? "l" : "", c.nosort ? "" : "bt-sort", on ? "on" : ""], scope: "col",
        "aria-sort": on ? (st.dir > 0 ? "ascending" : "descending") : null},
      c.nosort ? c.label : h("button", {type: "button", class: "bt-th", title: `${c.label} 순으로 정렬 (한 번 더 누르면 거꾸로)`,
        onclick: () => { if (st.col === c.id) st.dir = -st.dir; else { st.col = c.id; st.dir = 1; } st.page = 0; render(); }},
      c.label, on ? h("span", {"aria-hidden": "true"}, st.dir > 0 ? " ▾" : " ▴") : null));
      return th;
    })));
  }
  function cell(a, init) {
    const m = moneyOk(a, st.group);
    const n = a.trades || 0;
    const dash = h("span", {class: "muted", title: "딥시크·동전 봇은 다른 묶음과 섞인 목록에서 돈 숫자를 보이지 않습니다"}, "개수만");
    return h("tr", {class: ["click", a.kind === "random" ? "bt-flip" : ""], onclick: () => ctx.go("account", a.account_id)},
      h("td", {class: "num"}, a._rk == null ? "—" : fmt.int(a._rk)),
      h("td", {class: "l"}, h("a", {class: "bt-name", href: ctx.href("account", a.account_id), title: a.account_id,
        onclick: (e) => e.stopPropagation()}, fav.favMark("account", a.account_id), fmt.acctName(a)),
      st.group === "all" ? h("span", {class: "bt-g"}, groupKo(fmt.groupOf(a))) : null),
      h("td", {class: "num"}, m ? fmt.money(a.wallet ?? init) : dash),
      h("td", {class: ["num", m ? fmt.tone(a.ret) : ""]}, m ? fmt.pct(a.ret) : "—"),
      h("td", {class: "num"}, fmt.int(n)),
      h("td", {class: "num"}, n ? h("span", null, fmt.pct(a.win_rate ?? (a.wins || 0) / n, 0, false), h("small", {class: "bt-wl"}, ` ${fmt.int(a.wins || 0)}승 ${fmt.int(a.losses || 0)}패`)) : "—"),
      h("td", {class: "num"}, m && a.max_drawdown ? fmt.pct(a.max_drawdown, 1, false) : "—"),
      h("td", {class: "l"}, a.bust ? h("span", {class: "pp bad"}, "파산") : a.position ? posChip(a) : h("span", {class: "muted"}, "대기")),
      h("td", null, refTag(a, st.gs) || "—"));
  }
  function render() {
    head();
    const init = (st.gs && st.gs.initial) || 5000;
    let rows = st.q ? st.rows.filter((a) => fmt.acctName(a).toLowerCase().includes(st.q) || String(a.account_id).toLowerCase().includes(st.q)) : st.rows;
    rows = sortRows(rows, st.col, st.dir, st.group);
    const pages = Math.max(1, Math.ceil(rows.length / PAGE));
    st.page = Math.max(0, Math.min(st.page, pages - 1));
    const s0 = st.page * PAGE, part = rows.slice(s0, s0 + PAGE);
    put(tbody, part.length ? part.map((a) => cell(a, init)) : h("tr", null, h("td", {colspan: String(COLS.length), class: "l muted"}, "맞는 계좌가 없습니다")));
    info.textContent = rows.length ? `${fmt.int(s0 + 1)}–${fmt.int(s0 + part.length)} / ${fmt.int(rows.length)}` : "0 / 0";
    prev.disabled = st.page === 0; next.disabled = st.page >= pages - 1;
    bar.hidden = rows.length <= PAGE;
    put(note, h("b", null, "참고"), " · 상태의 % = 열린 포지션의 지금 ROE (마크 가격, 수수료 전) · 동전 ▲▼ = 같은 봉 동전 봇 중앙값보다 위·아래 · 판정은 30일째",
      st.group === "all" ? " · 섞인 목록에서 딥시크·동전 봇은 개수만 (순위 없이 맨 뒤)" : "");
    if (o.onRender) o.onRender();
  }
  return {
    el,
    /** only: null, or the ★ 즐겨찾기만 test of a row (home-shared rankList favPred; conv-b). */
    set(board, gs, group, only) {
      if (group !== st.group) st.page = 0;
      st.group = group; st.gs = gs;
      let rows = derive.ranked(board, group);
      if (only) rows = rows.filter(only);
      rows = derive.mixedOrder(rows.filter((a) => !derive.unranked(a)).sort((x, y) => y.ret - x.ret).concat(rows.filter(derive.unranked)), group);
      let rk = 0;
      st.rows = rows.map((a, i) => ({...a, _at: i, _rk: derive.unranked(a) || derive.countOnlyIn(a, group) ? null : ++rk}));
      render();
    },
  };
}

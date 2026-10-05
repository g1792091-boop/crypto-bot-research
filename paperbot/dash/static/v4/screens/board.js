// 순위표 (builder A, CONTRACT.md section 4): group cards (+ 전체) → stats of the chosen group → top 5 / bottom 5 → the
// searchable full list (timeframe filter, sort, 10 per page) → 봉별 요약 ('참고') → the extra accounts → CSV.
// #/board?g=<core|ds|m5|coin|extra|all> selects the group (home links here); update(params) keeps the screen in place.
// HONESTY: coin-flip comparisons are '참고' (neutral colours, refNote); DeepSeek rows carry only the bare 참고 pill;
// extras are never compared; every money table has assume().
import {h, put, ui, fmt, derive, motion, local} from "../core/pb.js";
import {groupCards, topBottom, rankList, groupKo, savedGroup, expInfo, extraPills, ORDER, TF_ORDER} from "./home-shared.js";

let current = null;          // the mounted screen's group setter (update() uses it)
const okGroup = (g) => (ORDER.includes(g) || g === "all" ? g : null);

export async function mount(el, ctx) {
  ctx.setTitle("순위표");
  const st = {sel: okGroup((ctx.params.query || {}).g) || savedGroup("board-group"), board: null, gs: null, summary: null};
  const href = (n, a, q) => ctx.href(n, a, q);

  const csv = [h("a", {class: "btn-line", href: "/api/export/board.csv", download: "paper-board.csv", title: "모든 계좌의 지금 순위 (엑셀로 열림)"}, "순위표 CSV"),
    h("a", {class: "btn-line", href: "/api/export/trades.csv", download: "paper-trades.csv", title: "닫힌 거래 전부 (엑셀로 열림)"}, "전체 거래 CSV")];
  el.append(ui.screenHead("순위표", "묶음을 고르면 아래가 모두 그 묶음으로 바뀝니다", h("span", {class: "row wrap board-csv"}, csv)));

  const groups = groupCards({onPick: (id) => setGroup(id, true)});
  const allBtn = h("button", {type: "button", class: "btn-line board-all", "aria-pressed": "false", onclick: () => setGroup("all", true)}, "전체 보기");
  el.append(h("section", {class: "home-sec", "aria-label": "묶음"}, h("div", {class: "home-sec-row"}, ui.plate("묶음"),
    h("span", {class: "muted home-hint"}, "같은 봉 동전 봇 중앙값과 비교한 숫자는 모두 참고입니다"), h("span", {class: "grow"}), allBtn), groups));

  const stats = h("div", {class: "stats s4 board-stats"});
  const tb = topBottom(ctx, {full: true});
  const tbCard = ui.card({plate: "상위·하위", cls: "board-tb"}, stats, tb);
  const list = rankList(ctx, {sorts: true, full: true, memo: "board-list"});
  const refBox = h("div");
  const listCard = ui.card({plate: "전체 목록", acts: [list.countEl]}, list.el, refBox,
    ui.assume(null, "수익률·잔고는 닫힌 거래 기준 (열린 포지션 손익 제외)"));
  const tfBody = h("div", {class: "board-tfbody"});
  const tfCard = ui.card({plate: "봉별 요약", sub: "참고"}, tfBody,
    h("p", {class: "muted home-small"}, "위·아래 = 같은 봉 동전 봇 3개의 잔고 중앙값보다 위·아래인 계좌 수 (참고, 판정 아님). 동전 봇 최고 = 그 봉 동전 봇 중 가장 큰 잔고."),
    ui.assume());
  const xBody = h("div");
  const xCard = ui.card({plate: "추가 계좌", sub: "복제·새 매매법 · 늦게 시작해 따로 셈"}, xBody, ui.assume());
  xCard.hidden = true;
  el.append(h("div", {class: "board-grid"}, tbCard, listCard), h("div", {class: "board-grid2"}, tfCard, xCard));

  // ---------------------------------------------------------------- renderers
  function renderStats() {
    const b = st.board, gs = st.gs;
    const rows = derive.ranked(b, st.sel === "extra" ? "extra" : st.sel);
    const init = gs.initial;
    put(stats,
      ui.stat("계좌", fmt.int(rows.length), groupKo(st.sel)),
      ui.stat("포지션 중", fmt.int(rows.filter((a) => a.position).length), "지금 열린 포지션"),
      ui.stat("시작보다 많은 계좌", fmt.int(rows.filter((a) => (a.wallet ?? init) > init).length), `잔고 ${fmt.int(init)} 넘음`),
      ui.stat("파산", fmt.int(rows.filter((a) => a.bust).length), "잔고 10 USDT 미만, 정지"));
  }

  function median(xs) { return derive.median(xs); }
  function tfTable() {
    const b = st.board, gs = st.gs, init = gs.initial;
    const accts = (b.accounts || []);
    const flipsBy = (tf) => accts.filter((a) => a.kind === "random" && a.timeframe === tf);
    const best = (rows) => rows.reduce((m, a) => (!m || (a.wallet ?? init) > (m.wallet ?? init) ? a : m), null);
    const bestCell = (a) => (a ? h("a", {class: "board-best", href: href("account", a.account_id), title: a.account_id},
      h("span", {class: "nm2"}, fmt.acctName(a)), " ", h("b", {class: ["num", fmt.tone((a.wallet ?? init) - init)]}, fmt.money(a.wallet ?? init))) : "—");
    const vs = (rows) => {
      const n = rows.filter((a) => gs.flipMedByTf[a.timeframe] != null).length;
      if (!n) return "—";
      const up = rows.filter((a) => (a.wallet ?? init) > gs.flipMedByTf[a.timeframe]).length;
      const dn = rows.filter((a) => (a.wallet ?? init) < gs.flipMedByTf[a.timeframe]).length;
      return `위 ${fmt.int(up)} · 아래 ${fmt.int(dn)}`;
    };
    const common = [
      {label: "계좌", get: (r) => fmt.int(r.rows.length)},
      {label: "포지션", get: (r) => fmt.int(r.rows.filter((a) => a.position).length)},
      {label: "파산", get: (r) => fmt.int(r.rows.filter((a) => a.bust).length)},
      {label: "잔고 중앙값", get: (r) => fmt.money(median(r.rows.map((a) => a.wallet ?? init)))},
      {label: "최고 계좌", l: true, get: (r) => bestCell(best(r.rows))},
    ];
    if (st.sel === "all") {
      const rows = ORDER.filter((g) => gs.groups[g]).map((g) => ({key: groupKo(g), g, rows: accts.filter((a) => fmt.groupOf(a) === g)}));
      return ui.table([{label: "묶음", l: true, get: (r) => r.key}, ...common,
        {label: "위·아래 (참고)", get: (r) => (r.g === "coin" || r.g === "extra" ? "—" : vs(r.rows.filter((a) => a.kind !== "random")))}], rows);
    }
    const mine = accts.filter((a) => fmt.groupOf(a) === st.sel);
    const rows = TF_ORDER.filter((tf) => mine.some((a) => a.timeframe === tf)).map((tf) => ({key: fmt.tfKo(tf), tf, rows: mine.filter((a) => a.timeframe === tf)}));
    const cols = [{label: "봉", l: true, get: (r) => r.key}, ...common];
    if (st.sel !== "extra") {
      cols.push({label: "동전 봇 중앙값", get: (r) => fmt.money(gs.flipMedByTf[r.tf])},
        {label: "동전 봇 최고", get: (r) => fmt.money(b.best_random && b.best_random[r.tf] != null ? b.best_random[r.tf] : best(flipsBy(r.tf)) && best(flipsBy(r.tf)).wallet)});
    }
    if (st.sel !== "coin" && st.sel !== "extra") cols.push({label: "위·아래 (참고)", get: (r) => vs(r.rows.filter((a) => a.kind !== "random"))});
    return rows.length ? ui.table(cols, rows) : ui.empty("계좌가 없습니다");
  }

  function renderExtras() {
    const xs = derive.ranked(st.board, "extra");
    xCard.hidden = !xs.length;
    if (!xs.length) { put(xBody); return; }
    const pg = ui.pager({size: 10, row: (a, i) => h("a", {class: "lrow click home-row board-xrow", role: "listitem", href: href("account", a.account_id), title: a.account_id},
      h("span", {class: "rk"}, fmt.int(i + 1)), h("span", {class: "lname"}, ui.acctLabel(a)),
      h("span", {class: ["ret", "num", fmt.tone(a.ret)]}, fmt.pct(a.ret)),
      h("span", {class: "meta"}, ...extraPills(a), a.parent ? h("span", null, `원본 ${fmt.idName(a.parent)}`) : null,
        a.created_ts ? h("span", null, `${fmt.mmdd(a.created_ts)} 시작`) : null, h("span", null, `거래 ${fmt.int(a.trades)}`),
        ui.smallSample(a.trades), a.bust ? ui.pill("파산", "bad") : null,
        a.rule_ko || a.description_ko ? h("span", {class: "board-rule"}, String(a.rule_ko || a.description_ko)) : null))});
    pg.set(xs);
    put(xBody, pg.el);
  }

  function render(animate) {
    const b = st.board, gs = st.gs;
    if (!b || !gs) return;
    if (st.sel !== "all" && !gs.groups[st.sel]) st.sel = "core";
    groups.update(b, gs, st.sel);
    allBtn.setAttribute("aria-pressed", String(st.sel === "all"));
    allBtn.textContent = `전체 ${fmt.int(derive.ranked(b, "all").length)}개 보기`;
    renderStats();
    tb.set(b, gs, st.sel);
    list.set(b, gs, st.sel, !animate);
    put(tfBody, tfTable());
    tfCard.querySelector(".card-h .sub").textContent = `${groupKo(st.sel)} · 참고`;
    renderExtras();
    const x = expInfo(st.summary);
    put(refBox, ui.refNote(x && x.verdictTs,
      st.sel === "ds" ? "딥시크 계좌는 계좌마다 비교하지 않고 묶음 숫자만 참고로 봅니다." : null));
    if (animate) { motion.swap(tb); motion.swap(tfBody); }
  }
  function setGroup(id, user) {
    id = okGroup(id);
    if (!id) return;
    st.sel = id;
    local.set("board-group", id);
    if (user) { try { window.history.replaceState(null, "", href("board", null, {g: id})); } catch { /* keep the old hash */ } }
    render(true);
  }
  current = (params) => { const g = okGroup((params.query || {}).g); if (g && g !== st.sel) setGroup(g, false); };
  ctx.track(() => { current = null; });

  const [b0] = await Promise.all([ctx.store.need("board", 60000).catch((e) => e), ctx.store.need("summary", 60000).catch(() => null)]);
  if (!ctx.alive()) return;
  if (b0 instanceof Error) el.insertBefore(ui.errorBox(b0, () => ctx.store.refresh("board").catch(() => {})), el.children[1] || null);
  ctx.watch("summary", (s) => { if (s) { st.summary = s; render(false); } });
  ctx.watch("board", (b) => { if (b) { st.board = b; st.gs = derive.groupStats(b); render(false); } });
}

export function update(params) { if (current) current(params); }

export function unmount() { current = null; }

// #/rank 순위표 (the rule bot's v4 board, as the demo lab's): filters (종류, 봉, 성격, 계좌, 찾기), one card per account
// role (the pool mean of its accounts' trades, the checkpoints' unit; how many beat their own 후보), and the dense sortable table of the 38
// picks (or of the chosen role's accounts) with each one's comparison against its own 기본값 and 동전. A row opens the
// account. Data: the shared snapshot. HONESTY: fewer than 30 closed trades says 표본 적음; a comparison is a mark, not a
// verdict (the verdicts are 점검 진행's).
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import * as LK from "../lk.js";
import {ROLES, ROLE_KO, TFS, tfKo, STYLE_KO} from "../labels.js";

/** The comparison mark of a row: hidden money says 숨김; a 1/4 row is compared by drawdown only (on its card). */
function markOf(r, ok) {
  if (LK.dsHidden(r.a) && r.a.trades) return LK.vsMark(null, null, {hidden: true});
  if (r.a.role === "quarter") return LK.vsMark(null, null, {title: "1/4 크기는 낙폭으로만 비교 (계좌 종류 카드)"});
  return LK.vsMark(ok);
}

export async function mount(el, ctx) {
  try { await ctx.meta(); } catch (e) { /* codes */ }
  const q = ctx.params.query || {};
  const st = {kind: q.kind || "all", tf: q.tf || "all", style: q.style || "all", role: ROLES.includes(q.role) ? q.role : "cand"};
  const save = () => ctx.setQuery(Object.fromEntries(Object.entries(st).filter(([k, v]) => v !== "all" && !(k === "role" && v === "cand"))));
  const cards = K4.groupCards({label: "계좌 고르기", medLabel: "묶음 평균", onPick: (id) => { st.role = id; save(); paint(); }});
  const kindSeg = ui.seg([{id: "all", label: "전체"}, {id: "core", label: "기존 36"}, {id: "ds", label: "딥시크"}], st.kind, (v) => { st.kind = v; save(); paint(); }, {label: "종류"});
  const tfSeg = ui.seg([{id: "all", label: "전체"}, ...TFS.map((t) => ({id: t, label: tfKo(t)}))], st.tf, (v) => { st.tf = v; save(); paint(); }, {label: "봉"});
  const styleSeg = ui.seg([{id: "all", label: "전체"}, ...Object.entries(STYLE_KO).map(([k, v]) => ({id: k, label: v}))], st.style,
    (v) => { st.style = v; save(); paint(); }, {label: "성격"});
  const info = h("p", {class: "note"});
  const board = K4.boardTable({
    page: 40,
    sort: {id: "mean", dir: -1},
    search: {placeholder: "매매법 찾기 (한글 또는 코드)", match: (r, s) => `${LK.stratKo(r.a.name)} ${r.a.name} ${r.a.tf}`.toLowerCase().includes(s)},
    onRow: (r) => { location.hash = `#/account/${encodeURIComponent(r.a.id)}`; },
    rowCls: (r) => (r.a.bust ? "cl-bust" : ""),
    cols: [
      {id: "rk", label: "#", sort: (r) => r.rank, dir: 1, get: (r) => h("span", {class: "num muted"}, r.rank ? String(r.rank) : "—")},
      {id: "name", label: "매매법 · 봉", l: true, sort: (r) => `${LK.stratKo(r.c.name)} ${r.c.tf}`, get: (r) => LK.pickName(r.c, {code: false})},
      {id: "kind", label: "종류", l: true, sort: (r) => r.c.kind, get: (r) => LK.kindChip(r.c.kind)},
      {id: "n", label: "거래", sort: (r) => r.a.trades, get: (r) => h("span", {class: "num"}, fmt.int(r.a.trades), LK.smallN(r.a.trades) ? h("small", {class: "muted"}, " 적음") : null)},
      {id: "win", label: "승률", sort: (r) => LK.winRate(r.a), get: (r) => LK.winTxt(r.a)},
      {id: "mean", label: "한 번 평균", sort: (r) => r.a.mean_ret, get: (r) => LK.ret(r.a.mean_ret, {hiddenIf: LK.dsHidden(r.a)})},
      {id: "vb", label: "기본값보다", sort: (r) => (r.vsBase == null ? null : r.vsBase ? 1 : 0), get: (r) => markOf(r, r.vsBase)},
      {id: "vf", label: "동전보다", sort: (r) => (r.vsFlip == null ? null : r.vsFlip ? 1 : 0), get: (r) => markOf(r, r.vsFlip)},
      {id: "v", label: "후보 기준", title: "후보 계좌의 기준 (30번 이상: 평균 > 0 · 기본값보다 · 동전보다)",
        get: (r) => h("span", {class: "cl-vcell"}, LK.verdictPill(r.j), r.j && r.j.band && r.j.band.below ? LK.bandMark(r.j) : null)},
      {id: "band", label: "백테스트 대비", title: "후보의 한 번 평균이 자기 5년 시험 기간 범위(같은 거래 수의 하위 5% · 중앙값)의 어디쯤인지 (참고)",
        sort: (r) => (r.a.role === "cand" ? LK.bandPos(r.a).key : null), get: (r) => (r.a.role === "cand" ? LK.bandPos(r.a).el : "—")},
      {id: "wallet", label: "잔고", sort: (r) => r.a.wallet, get: (r) => LK.wallet(r.a)},
      {id: "dd", label: "최대 낙폭", sort: (r) => r.a.max_dd, get: (r) => LK.ddTxt(r.a)},
      {id: "style", label: "성격", l: true, sort: (r) => r.style || "", get: (r) => LK.styleChip(r.style) || "—"},
      {id: "exit", label: "익절 · 손절", l: true, get: (r) => h("span", {class: "cl-exit", title: r.a.exit_ko}, LK.exitShort(r.a.exit_ko))},
    ]});
  el.append(
    ui.screenHead("순위표", "후보 38개와 비교 계좌 · 카드를 누르면 그 계좌들로 표가 바뀝니다",
      h("button", {class: "btn-line", type: "button", onclick: csv}, "순위표 CSV")),
    h("div", {class: "dl-fields"}, ui.field("종류", kindSeg), ui.field("봉", tfSeg), ui.field("성격", styleSeg)),
    h("section", {class: "k4-sec", "aria-label": "계좌 종류"}, K4.secRow("계좌 5종류", "같은 후보에서 갈라진 다섯 계좌 · 큰 숫자 = 그 계좌들의 모든 거래를 모은 한 번 평균 (점검과 같은 계산)"), cards),
    ui.card({plate: "표", sub: "머리글을 누르면 그 순서로 · 줄을 누르면 계좌 자세히"}, board.el, info));

  let last = [];
  function rows(d) {
    const ix = LK.index(d);
    let picks = ix.cands.filter((c) => (st.kind === "all" || c.kind === st.kind) && (st.tf === "all" || c.tf === st.tf));
    if (st.style !== "all") picks = picks.filter((c) => (LK.pickMeta(c.id) || {}).style === st.style);
    const out = picks.map((c) => {
      const set = ix.sets[c.id];
      const a = set[st.role] || c;
      return {c, a, set, j: ix.judge[c.id], style: (LK.pickMeta(c.id) || {}).style,
        vsBase: st.role === "base" || st.role === "quarter" ? null : LK.better(a, set.base),
        vsFlip: st.role === "flip" || st.role === "quarter" ? null : LK.better(a, set.flip)};
    });
    const ranked = out.filter((r) => r.a.mean_ret != null && r.a.trades).sort((x, y) => y.a.mean_ret - x.a.mean_ret);
    ranked.forEach((r, i) => { r.rank = i + 1; });
    return out;
  }
  function paintCards(d) {
    const ix = LK.index(d);
    const picks = ix.cands.filter((c) => (st.kind === "all" || c.kind === st.kind) && (st.tf === "all" || c.tf === st.tf)
      && (st.style === "all" || (LK.pickMeta(c.id) || {}).style === st.style));
    cards.update(ROLES.map((role) => {
      const accts = picks.map((c) => ix.sets[c.id][role]).filter(Boolean);
      // the pool mean (WATCH_PREREG's unit): every closed trade of these accounts counted once = trades-weighted
      const shown = accts.filter((a) => a.mean_ret != null && a.trades);
      const n = shown.reduce((s, a) => s + a.trades, 0);
      const pooled = n ? shown.reduce((s, a) => s + a.trades * a.mean_ret, 0) / n : null;
      const hiddenN = accts.filter((a) => a.mean_ret == null && a.trades).length;
      // 1/4 크기 is a size check: compared by drawdown (its per-trade result is on another scale)
      const calmer = (a, c) => (a && c && a.max_dd != null && c.max_dd != null && a.trades && c.trades ? a.max_dd < c.max_dd : null);
      const cmp = role === "quarter" ? calmer : LK.better;
      const beat = role === "cand" ? null : picks.filter((c) => cmp(ix.sets[c.id][role], c) === true).length;
      const comparable = role === "cand" ? null : picks.filter((c) => cmp(ix.sets[c.id][role], c) != null).length;
      return {id: role, name: ROLE_KO[role], count: `${fmt.int(accts.length)}계좌 · 거래 ${fmt.int(accts.reduce((s, a) => s + a.trades, 0))}번` +
          (hiddenN ? ` (금액 숨김 ${fmt.int(hiddenN)}계좌 빼고 평균)` : ""),
        med: pooled == null ? null : pooled * 100,
        vs: role === "cand" ? "커스텀값 + 커스텀 익절·손절" : role === "quarter" ? `후보보다 덜 흔들린 계좌 ${fmt.int(beat)}/${fmt.int(comparable)}`
          : `후보보다 나은 계좌 ${fmt.int(beat)}/${fmt.int(comparable)}`,
        ref: role === "flip",
        foot: `파산 ${fmt.int(accts.filter((a) => a.bust).length)} · 포지션 ${fmt.int(accts.filter((a) => a.open).length)}`,
        title: `${ROLE_KO[role]}: 이 계좌들로 표를 바꿉니다`};
    }), st.role);
  }
  function paint() {
    const d = LK.league();
    if (!d || !d.accounts) { put(info, "준비 중"); return; }
    paintCards(d);
    last = rows(d);
    board.set(last, true);
    info.textContent = `${ROLE_KO[st.role]} 계좌 ${last.length}개 · 거래 한 번 평균 = 닫힌 거래마다 그 직전 지갑 대비 손익의 평균 · ` +
      "기본값보다 / 동전보다 = 같은 후보의 그 계좌와 비교 (참고)";
  }
  function csv() {
    K4.downloadCsv(`candleague-rank-${st.role}.csv`, ["account", "strategy", "tf", "kind", "exit", "trades", "wins", "mean_per_trade", "wallet", "max_dd"],
      last.map((r) => [r.a.id, r.a.name, r.a.tf, r.a.kind, r.a.exit, r.a.trades, r.a.wins, r.a.mean_ret ?? "", r.a.wallet ?? "", r.a.max_dd ?? ""]));
  }
  ctx.onLeague(paint);
}

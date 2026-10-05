// Shared pieces of the 홈 group (home, board, checkpoint; builder A): the group cards, a ranking row, the ranked list
// with its filters, and the judged-account progress for the checkpoint. Everything reads /api/board through
// derive.groupStats / derive.ranked, so 홈, 순위표 and 판정 show the same numbers. DOM only through h() / ui.*.
//
// HONESTY (CONTRACT.md section 1): comparisons with the coin flips are '참고' pills in neutral colours (never a pass or
// fail before /api/checkpoint says ready); a DeepSeek account gets nothing per account beyond the bare '참고' pill;
// late-started extras are never compared; small samples say 표본 적음.
import {h, put, ui, fmt, derive, local, stratFigure} from "../core/pb.js";

// wave 2 ⑦: the strategy's own pixel character in front of its name (no idle motion in lists)
const fig = (a, size) => stratFigure({strategy: a.strategy, kind: a.kind, size, cls: "row-fig"});

// ---------------------------------------------------------------- names the server does not send yet
// DeepSeek family names live in core/names.js (fmt.familyKo); /api/board drops accounts.data (NEEDS SERVER #1).
export const famKo = (a) => fmt.familyKo(a);

export const ORDER = ["core", "ds", "m5", "coin", "extra"];
export const groupKo = (id) => (id === "all" ? "전체" : fmt.GROUP_KO[id] || id);
export const TF_ORDER = fmt.TF_ORDER;

// The judged timeframes per kind: /api/board run_shape.judged_by_group (counted from the accounts table) when the
// server sends it, else these copies of config.V4_GROUPS "judged". 4h = observation only, coin flips = the yardstick,
// extras: their own start. MIN_TRADES = checkpoint.MIN_TRADES (tests/test_dash_v4.py ties the two).
export const JUDGED = {strategy: ["15m", "30m", "1h"], ds200: ["15m", "30m", "1h"], reel: ["5m"]};
const KIND_GROUP = {strategy: "core", ds200: "ds200", reel: "reel"};      // run_shape group keys (paperbot/groups.py)
export const MIN_TRADES = 30;
/** The judged timeframes of a kind, from the server's run shape when it has them. */
export function judgedTfs(board, kind) {
  const jb = board && board.run_shape && board.run_shape.judged_by_group;
  const v = jb && jb[KIND_GROUP[kind]];
  return Array.isArray(v) && v.length ? v : JUDGED[kind] || [];
}
export const SMALL = MIN_TRADES;          // 표본 적음 below the verdict's own floor

/** The selected group, remembered per viewer (a convenience only). */
export const savedGroup = (key, d = "core") => {
  const v = local.get(key, d);
  return ORDER.includes(v) || v === "all" ? v : d;
};

// ---------------------------------------------------------------- the D+n numbers (same rules as the top chip)
const DAY = 86400000;
export function expInfo(s, now = Date.now()) {
  if (!s || s.start == null) return null;
  const rs = s.restart || {};
  const cp = s.next_checkpoint || {};
  const day = rs.ready ? rs.day : (s.day || 1) - 1;
  const of = rs.ready ? rs.of : s.period_days || 30;
  const verdictTs = rs.ready ? rs.verdict_ts : cp.ts;
  const left = verdictTs ? Math.max(0, Math.ceil((verdictTs - now) / DAY)) : null;
  return {day, of, verdictTs, left, observing: !!s.observing, observeUntil: s.observe_until, k: cp.k || 1};
}

/** A verdict's UTC date "2026-10-28" (00:00 UTC = 09:00 KST that day) -> "10월 28일 (수)". */
export function verdictDate(d) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(d || ""));
  return m ? fmt.date(Date.UTC(+m[1], +m[2] - 1, +m[3])) : String(d || "—");
}

// ---------------------------------------------------------------- pills
/** The 참고 mark of one account: a small neutral glyph (never green / red: a comparison before the verdict is never a
 *  pass or a fail); the list's foot explains it once (vsFoot). Coin flips and late extras say what they are; a
 *  DeepSeek account gets nothing per account (group medians only). */
export function refTag(a, gs) {
  const g = fmt.groupOf(a);
  if (a.kind === "random") return h("span", {title: "동전 봇은 판정 대상이 아니라 비교 기준입니다"}, "비교 기준");
  if (g === "extra") return h("span", {title: "늦게 시작해 처음부터 돈 동전 봇과 잔고를 비교하지 않습니다"}, "늦게 시작");
  if (a.kind === "ds200") return null;
  const med = gs && gs.flipMedByTf ? gs.flipMedByTf[a.timeframe] : null;
  if (med == null) return null;
  const w = a.wallet == null ? (gs.initial || 5000) : a.wallet;
  const [g1, t] = w > med ? ["▲", "위"] : w < med ? ["▼", "아래"] : ["=", "같음"];
  return h("span", {class: "vsg", title: `참고 · 같은 봉 동전 봇 중앙값보다 ${t} · 판정 아님 (판정은 30일째)`,
    "aria-label": `참고: 같은 봉 동전 봇 중앙값보다 ${t}`}, "동전 ", h("b", {"aria-hidden": "true"}, g1));
}
/** The one 참고 caption under a list whose rows carry the ▲▼ glyph (null for the groups that have none). */
export function vsFoot(group) {
  if (group === "ds" || group === "coin" || group === "extra") return null;
  return h("p", {class: "assume home-vsfoot"}, h("b", null, "참고"), " · 동전 ▲▼ = 같은 봉 동전 봇 중앙값보다 위·아래 · 판정은 30일째",
    group === "all" ? " · 딥시크는 계좌마다 표시 안 함" : "");
}

/** Pills of a copy / new-strategy account and the runner's status when it is not running normally. */
export function extraPills(a) {
  if (fmt.groupOf(a) !== "extra") return [];
  const out = [a.kind === "copy" ? ui.pill("복제", "accent", "원본과 같고 한 가지만 바꾼 새 모의 계좌")
    : ui.pill("새 매매법", "accent", "새 매매법 연구실에서 통과한 매매법의 모의 계좌")];
  if (a.extra_status === "suspended") out.push(ui.pill("멈춤(보류)", "warn", "새 진입 없음, 열린 포지션은 규칙대로 관리"));
  if (a.extra_status === "held") out.push(ui.pill("정지(동결)", "bad", "저장된 상태 그대로 동결"));
  if (a.orphan) out.push(ui.pill("제안 상태와 달리 실행 중", "bad", "에이전트 쪽 제안이 없거나 승인 상태가 아님"));
  return out;
}

// ---------------------------------------------------------------- one ranking row
/**
 * rankRow(a, {gs, rk, href, showGroup, full}) -> a.lrow (a link to the account).
 * a: a derive.ranked() row (has .ret). full: the 순위표 meta (W-L, max drawdown, open position).
 */
export function rankRow(a, o) {
  // compact (home's 상위·하위): one line (rank, timeframe + name, return); a small sample is a dimmed row (the list's
  // caption says so, the row's title gives the count), a bust keeps its pill; the full meta is on 순위표
  if (o.compact) {
    const small = (a.trades || 0) < SMALL;
    return h("a", {class: ["lrow", "click", "home-row", "compact", small ? "thin" : ""], href: o.href(a.account_id), role: "listitem",
      title: a.account_id, "aria-label": `${fmt.acctName(a)} ${fmt.tfKo(a.timeframe)} ${fmt.pct(a.ret)} · 거래 ${fmt.int(a.trades)}건${small ? " · 표본 적음" : ""}${a.bust ? " · 파산" : ""}`},
    h("span", {class: "rk"}, fmt.int(o.rk)),
    h("span", {class: "lname"}, fig(a, 18), ui.acctLabel(a), a.bust ? ui.pill("파산", "bad", "잔고 10 USDT 미만으로 정지") : null),
    h("span", {class: ["ret", "num", fmt.tone(a.ret)]}, fmt.pct(a.ret)));
  }
  // one meta line: "거래 22 · 낙폭 1.2%" (+ W-L, wallet, open position on the 순위표); the timeframe leads the name
  const words = [];
  if (o.showGroup) words.push(groupKo(fmt.groupOf(a)));
  words.push(`거래 ${fmt.int(a.trades)}`);
  if (o.full && a.trades) words.push(`${fmt.int(a.wins)}승 ${fmt.int(a.losses)}패`);
  if (o.full && a.wallet != null) words.push(`잔고 ${fmt.money(a.wallet)}`);
  if (a.max_drawdown) words.push(`낙폭 ${fmt.pct(a.max_drawdown, 1, false)}`);
  const meta = [h("span", null, words.join(" · "))];
  if (o.full && a.position) meta.push(posChip(a));
  meta.push(ui.smallSample(a.trades, SMALL));
  if (a.bust) meta.push(ui.pill("파산", "bad", "잔고 10 USDT 미만으로 정지"));
  meta.push(refTag(a, o.gs), ...extraPills(a));
  return h("a", {class: "lrow click home-row", href: o.href(a.account_id), role: "listitem", title: a.account_id},
    h("span", {class: "rk"}, fmt.int(o.rk)),
    h("span", {class: "lname"}, fig(a, 20), ui.acctLabel(a)),
    h("span", {class: ["ret", "num", fmt.tone(a.ret)]}, fmt.pct(a.ret)),
    h("span", {class: "meta"}, meta));
}

// ---------------------------------------------------------------- the open-position chip with its live ROE
/** The groups whose open position may show money in a mixed list (기존 36 / 5분봉 / 추가; DeepSeek and the coin flips:
 *  the chip names the position only, D10/D11). */
export const ROE_GROUPS = new Set(["core", "m5", "extra"]);
/** '● LTC 숏 30배' (+ a live ROE slot '+20.4%' that paintRoe fills from the mark price, money groups only). */
export function posChip(a) {
  const p = a.position;
  const money = ROE_GROUPS.has(fmt.groupOf(a));
  return h("span", {class: ["home-pos", money ? "roe-live" : ""], dataset: money ? {aid: a.account_id} : null,
    title: money ? "열린 포지션 · 지금 마크 가격 기준 ROE (수수료 전, 5초마다)" : "열린 포지션 (딥시크·동전 봇은 손익을 보이지 않음)"},
  `● ${fmt.coin(p.symbol)} ${fmt.sideKo(p.side)} ${fmt.lev(p.leverage)}`, money ? h("b", {class: "home-roe num"}) : null);
}
/** Fill every live chip under root: ROE = unrealized P&L at the mark price / margin (derive.livePnl, before the exit
 *  fee). markOf(symbol) -> mark or null. A chip whose mark is unknown stays without a number (never a guess). */
export function paintRoe(root, board, markOf) {
  if (!root || !board) return;
  const chips = root.querySelectorAll(".home-pos.roe-live[data-aid]");
  if (!chips.length) return;
  const by = new Map((board.accounts || []).map((a) => [a.account_id, a]));
  for (const c of chips) {
    const a = by.get(c.dataset.aid);
    const u = a && a.position ? derive.livePnl(a.position, markOf(a.position.symbol)) : null;
    const b = c.querySelector(".home-roe");
    if (!b) continue;
    if (!u || !Number.isFinite(u.roe)) { b.textContent = ""; c.classList.remove("up", "down"); continue; }
    const txt = fmt.pct(u.roe, 1);
    if (b.textContent !== txt) { b.textContent = txt; c.classList.remove("tick"); void c.offsetWidth; c.classList.add("tick"); }
    c.classList.toggle("up", u.roe > 0);
    c.classList.toggle("down", u.roe < 0);
  }
}

// ---------------------------------------------------------------- group cards
function countLine(id, rows, flips5 = 0) {
  const n = rows.length;
  if (id === "m5") return `${fmt.int(n)}계좌 · 비교: 5분봉 동전 ${fmt.int(flips5)}개 (동전 봇에서 셈)`;
  if (id === "coin") {
    const f5 = rows.filter(fmt.isFlip5).length;
    return `${fmt.int(n)}계좌 · 봉마다 3개` + (f5 ? ` (5분봉 ${fmt.int(f5)}개 포함)` : "");
  }
  if (id === "ds") return `${fmt.int(n)}계좌 · 정의 ${fmt.int(new Set(rows.map((a) => a.strategy)).size)}개`;
  if (id === "core") return `${fmt.int(n)}계좌 · 매매법 ${fmt.int(new Set(rows.map((a) => a.strategy)).size)}개`;
  return `${fmt.int(n)}계좌`;
}

/**
 * groupCards({onPick, allLabel}) -> div with .update(board, gs, sel). Cards are built once and updated in place, so
 * the median counts to its new value (real data only) and focus stays where it was. allLabel: add a "전체" card.
 */
export function groupCards(o) {
  const el = h("div", {class: "home-groups", role: "group", "aria-label": "묶음 고르기"});
  const cards = new Map();
  let order = "";
  function make(id) {
    const g = fmt.GROUPS.find((x) => x.id === id) || {ko: groupKo(id), desc: ""};
    const cnt = h("span", {class: "gc"});
    const med = ui.liveNum(null, {format: "pct", tone: true, cls: "gm", flash: true});
    const vs = h("span", {class: "gs"});
    const foot = h("span", {class: "gb"});
    const line = h("span", {class: ["home-gline", id], "aria-hidden": "true"});
    const btn = h("button", {type: "button", class: "home-gcard", "aria-pressed": "false", title: g.desc || null,
      onclick: () => o.onPick(id)},
      h("span", {class: "gn"}, id === "all" ? o.allLabel || "전체" : g.ko), cnt,
      h("span", {class: "gmw"}, med, h("small", null, "중앙값")), line, vs, foot);
    return {btn, cnt, med, vs, foot, line, sig: ""};
  }
  /** sparks({group id: [ratio to the start ...]}): a small median line in each card (home: the race's own series,
   *  the group's colour); a card without a series keeps an empty slot. Drawn in once, redrawn only when it changed. */
  el.sparks = (series) => {
    for (const [id, c] of cards) {
      const v = series && series[id];
      const sig = v ? v.length + ":" + v[v.length - 1] : "";
      if (sig === c.sig) continue;
      const first = !c.sig;
      c.sig = sig;
      put(c.line, v ? ui.miniSpark(v, {w: 120, h: 22, base: 0, fluid: true, draw: first, label: `${groupKo(id)} 중앙값 흐름`}) : null);
    }
  };
  el.update = (board, gs, sel) => {
    const ids = ORDER.filter((id) => gs.groups[id]);
    if (o.allLabel) ids.push("all");
    for (const id of ids) {
      const c = cards.get(id) || make(id);
      cards.set(id, c);
      const rows = (board.accounts || []).filter((a) => (id === "all" ? fmt.groupOf(a) !== "extra" : fmt.groupOf(a) === id));
      const x = id === "all" ? null : gs.groups[id];
      if (id === "all") {
        const all = derive.ranked(board, "all");
        c.cnt.textContent = `${fmt.int(all.length)}계좌 · 묶음 섞어 보기`;
        c.med.update(derive.median(all.map((a) => a.ret)));
        put(c.vs, "모든 묶음을 한 목록으로");
        c.foot.textContent = `파산 ${fmt.int(all.filter((a) => a.bust).length)} · 포지션 ${fmt.int(all.filter((a) => a.position).length)}`;
      } else {
        const flips5 = (board.accounts || []).filter(fmt.isFlip5);
        c.cnt.textContent = countLine(id, rows, flips5.length);
        c.med.update(x.medRet);
        if (id === "coin") put(c.vs, "비교 기준 (판정 안 함)");
        else if (id === "extra") put(c.vs, "늦게 시작 · 비교 안 함");
        else if (id === "m5") put(c.vs, `5분봉 동전 ${fmt.int(flips5.length)}개 중앙값보다 위 ${fmt.int(x.above)}/${fmt.int(x.vsN)} `, ui.pill("", "ref"));
        else put(c.vs, `동전 봇 중앙값보다 위 ${fmt.int(x.above)}/${fmt.int(x.vsN)} `, ui.pill("", "ref"));
        c.foot.textContent = `파산 ${fmt.int(x.bust)} · 포지션 ${fmt.int(x.open)}`;
      }
      c.btn.setAttribute("aria-pressed", String(id === sel));
    }
    const sig = ids.join();
    if (sig !== order) { order = sig; put(el, ...ids.map((id) => cards.get(id).btn)); }
  };
  return el;
}

// ---------------------------------------------------------------- top 5 / bottom 5
/** topBottom(ctx, {full, compact}) -> {el, set(board, gs, group)}: the best and worst five of a group (one list when it
 *  has <= 10). compact: one-line rows (home). */
export function topBottom(ctx, o = {}) {
  const head = h("div", {class: "home-tbh"});
  const body = h("div", {class: "home-tb"});
  const foot = h("div");
  const el = h("div", {class: "stack tight"}, head, body, foot);
  const href = (id) => ctx.href("account", id);
  el.set = (board, gs, group) => {
    put(foot, o.compact ? h("p", {class: "assume home-vsfoot"}, h("b", null, "흐린 줄"), ` = 거래 ${MIN_TRADES}건 미만 (표본 적음) · 거래 수·낙폭·동전 봇 비교(참고)는 순위표에서`)
      : vsFoot(group));
    // day 0: accounts with no closed trade and no open position have no rank yet (one muted line, never a tie list)
    const {rows, waiting} = derive.rankedOnly(board, group);
    const n = rows.length;
    const row = (a, i) => rankRow(a, {gs, rk: i + 1, href, showGroup: group === "all", full: !!o.full, compact: !!o.compact});
    const wait = waiting ? h("p", {class: "muted home-small tb-wait"}, derive.waitingKo(waiting)) : null;
    if (!n && waiting) put(body, wait);
    else if (n <= 10) {
      put(body, h("div", {class: "home-tbcol"}, h("div", {class: "tb-h"}, h("b", null, groupKo(group)), h("span", null, `전체 ${fmt.int(n)}개`)),
        h("div", {role: "list"}, n ? rows.map(row) : ui.empty("계좌가 없습니다"))), wait);
    } else {
      put(body, 
        h("div", {class: "home-tbcol"}, h("div", {class: "tb-h"}, h("b", null, groupKo(group)), h("span", null, "상위 5")),
          h("div", {role: "list"}, rows.slice(0, 5).map(row))),
        h("div", {class: "home-tbcol"}, h("div", {class: "tb-h"}, h("b", null, groupKo(group)), h("span", null, "하위 5")),
          h("div", {role: "list"}, rows.slice(-5).map((a, i) => row(a, n - 5 + i)))), wait);
    }
  };
  return el;
}

// ---------------------------------------------------------------- the ranked list with filters
const SORTS = [
  {id: "ret", label: "수익률", key: (a) => -a.ret},
  {id: "trades", label: "거래 수", key: (a) => -(a.trades || 0)},
  {id: "win", label: "승률", key: (a) => -(a.win_rate ?? -1)},
  {id: "dd", label: "낙폭 작은 순", key: (a) => a.max_drawdown ?? 0},
  {id: "name", label: "이름", key: (a) => fmt.acctName(a)},
];

/**
 * rankList(ctx, {sorts, full, memo}) -> {el, set(board, gs, group, keepPage), countEl}
 * Search (name, code, family) + a timeframe filter (5분 only when the group has it) + optional sort; 10 per page
 * (never all 331 at once). Ranks are counted before the search, so a found account keeps its real rank.
 */
export function rankList(ctx, o = {}) {
  const st = {tf: o.memo ? local.get(o.memo + "-tf", "all") : "all", sort: o.memo ? local.get(o.memo + "-sort", "ret") : "ret",
    board: null, gs: null, group: "core", tfs: ""};
  const href = (id) => ctx.href("account", id);
  const tfBox = h("div", {class: "home-tfs"});
  const sortSel = o.sorts ? h("select", {class: "select", "aria-label": "정렬"},
    SORTS.map((s) => h("option", {value: s.id, selected: s.id === st.sort || null}, s.label))) : null;
  if (sortSel) sortSel.addEventListener("change", () => { st.sort = sortSel.value; if (o.memo) local.set(o.memo + "-sort", st.sort); apply(false); });
  const countEl = h("span", {class: "home-count"});
  const foot = h("div");
  const filters = h("div", {class: "home-filters"}, tfBox, sortSel ? h("label", {class: "home-sort"}, h("span", null, "정렬"), sortSel) : null);
  const list = ui.searchList({size: 10, placeholder: "이름·코드 찾기 (예: 돈치안, F9, REEL)",
    match: (a, q) => !a._flip && !a._flipMed && (fmt.acctName(a).toLowerCase().includes(q) || String(a.account_id).toLowerCase().includes(q)
      || (famKo(a) || "").toLowerCase().includes(q)),
    row: (a) => (a._flip || a._flipMed ? flipRow(a, href) : rankRow(a, {gs: st.gs, rk: a._rk, href, showGroup: st.group === "all", full: !!o.full})),
    filters, empty: "맞는 계좌가 없습니다"});
  list.input.setAttribute("enterkeyhint", "search");

  function tfSeg() {
    const rows = derive.ranked(st.board, st.group);
    const tfs = TF_ORDER.filter((tf) => rows.some((a) => a.timeframe === tf));
    const sig = st.group + "|" + tfs.join();
    if (!tfs.includes(st.tf)) st.tf = "all";
    if (sig === st.tfs) return;
    st.tfs = sig;
    const opts = [{id: "all", label: "모든 봉"}, ...tfs.map((tf) => ({id: tf, label: fmt.tfKo(tf)}))];
    put(tfBox, tfs.length > 1 ? ui.seg(opts, st.tf, (id) => { st.tf = id; if (o.memo) local.set(o.memo + "-tf", id); apply(false); }, {label: "봉 고르기", scroll: true}) : null);
  }
  function apply(keep) {
    if (!st.board) return;
    tfSeg();
    let rows = derive.ranked(st.board, st.group);
    if (st.tf !== "all") rows = rows.filter((a) => a.timeframe === st.tf);
    const s = SORTS.find((x) => x.id === st.sort) || SORTS[0];
    rows.sort((x, y) => { const p = s.key(x), q = s.key(y); return p < q ? -1 : p > q ? 1 : x.ret === y.ret ? 0 : y.ret - x.ret; });
    // accounts with no closed trade and no open position: after the ranked ones, '—' instead of a rank number
    rows = rows.filter((a) => !derive.unranked(a)).concat(rows.filter(derive.unranked));
    let rk = 0;
    rows.forEach((a) => { a._rk = derive.unranked(a) ? null : ++rk; });
    countEl.textContent = `${groupKo(st.group)}${st.tf !== "all" ? " · " + fmt.tfKo(st.tf) : ""} · ${fmt.int(rows.length)}계좌`;
    // 순위표 only (o.flips, wave 2 part B): the same-bar coin flips sit at their real place in a 수익률 list
    const fl = o.flips && st.sort === "ret" ? withFlips(rows, st) : null;
    list.set(fl ? fl.items : rows, keep);
    put(foot, vsFoot(st.group), fl ? flipFoot(fl, st.group) : null);
  }
  return {
    el: h("div", {class: "stack tight"}, list.el, foot), countEl,
    set(board, gs, group, keep = true) {
      const changed = group !== st.group;
      st.board = board; st.gs = gs; st.group = group;
      apply(keep && !changed);
    },
  };
}

// ---------------------------------------------------------------- coin flips inside the 순위표 list (ranked #5)
/**
 * withFlips(rows, st) -> {items, n, above, rows, med} or null. rows: the group's accounts, already sorted by 수익률.
 * 기존 36: every same-bar coin flip (15분~4시간; the list's timeframe filter applies) as a dimmed dashed row at its real
 * place; 5분봉: its three 5m flips; 딥시크: ONE line, the same-bar flips' median (no flip per DeepSeek account, CONTRACT
 * rule 3). The accounts keep their own rank numbers (1..n); a flip never takes a number.
 */
export function withFlips(rows, st) {
  const g = st.group;
  if (!["core", "m5", "ds"].includes(g) || !rows.length) return null;
  const tfs = new Set(rows.map((a) => a.timeframe));
  const flips = derive.ranked(st.board, "coin").filter((f) => tfs.has(f.timeframe) && (g === "m5" ? fmt.isFlip5(f) : !fmt.isFlip5(f))
    && (st.tf === "all" || f.timeframe === st.tf));
  if (!flips.length) return null;
  const marks = g === "ds"
    ? [{_flipMed: true, account_id: "__flip_median", ret: derive.median(flips.map((f) => f.ret)), n: flips.length,
      tfs: TF_ORDER.filter((tf) => flips.some((f) => f.timeframe === tf))}]
    : flips.map((f) => ({...f, _flip: true})).sort((x, y) => y.ret - x.ret);
  const items = [];
  let i = 0;
  for (const a of rows) {
    while (i < marks.length && marks[i].ret > a.ret) items.push(marks[i++]);
    items.push(a);
  }
  while (i < marks.length) items.push(marks[i++]);
  const medBy = {};
  for (const tf of tfs) { const xs = flips.filter((f) => f.timeframe === tf).map((f) => f.ret); if (xs.length) medBy[tf] = derive.median(xs); }
  const above = rows.filter((a) => medBy[a.timeframe] != null && a.ret > medBy[a.timeframe]).length;
  return {items, n: flips.length, above, rows: rows.length, med: g === "ds" ? marks[0].ret : null};
}

/** One coin-flip row (or the DeepSeek tab's one median line): dimmed, dashed, no rank number. */
export function flipRow(f, href) {
  if (f._flipMed) {
    return h("div", {class: "lrow home-row board-fliprow", role: "listitem", "aria-label": `동전 봇 ${f.n}개 중앙값 ${fmt.pct(f.ret)} (참고)`},
      h("span", {class: "rk board-coin", "aria-hidden": "true"}),
      h("span", {class: "lname"}, `동전 봇 중앙값 · ${f.tfs.map(fmt.tfKo).join("·")} ${fmt.int(f.n)}개`),
      h("span", {class: "ret num ink2"}, fmt.pct(f.ret)),
      h("span", {class: "meta"}, h("span", null, "비교 기준 · 참고 · 딥시크는 계좌마다 비교하지 않음")));
  }
  return h("a", {class: "lrow click home-row board-fliprow", href: href(f.account_id), role: "listitem",
    "aria-label": `동전 봇 ${fmt.tfKo(f.timeframe)} ${fmt.pct(f.ret)} (비교 기준, 순위 번호 없음)`},
    h("span", {class: "rk board-coin", "aria-hidden": "true"}),
    h("span", {class: "lname"}, ui.acctLabel(f)),
    h("span", {class: "ret num ink2"}, fmt.pct(f.ret)),
    h("span", {class: "meta"}, h("span", null, `동전 봇 · 거래 ${fmt.int(f.trades)}`), f.bust ? ui.pill("파산", "thin", "동전 봇도 파산할 수 있습니다") : null,
      h("span", null, "비교 기준 (순위 번호 없음)")));
}

/** The line under the list: "동전 봇 n개 자리 · 같은 봉 동전 봇 중앙값보다 위 매매법 a/b개 (참고)". */
export function flipFoot(fl, group) {
  return h("p", {class: "assume home-vsfoot board-flipfoot"}, h("span", {class: "board-coin", "aria-hidden": "true"}),
    group === "ds" ? `동전 봇 중앙값 줄 1개 (같은 봉 ${fmt.int(fl.n)}개) · 자기 봉의 동전 봇 중앙값보다 위 딥시크 ${fmt.int(fl.above)}/${fmt.int(fl.rows)}개`
      : `동전 봇 ${fmt.int(fl.n)}개 자리 · 같은 봉 동전 봇 중앙값보다 위 ${group === "m5" ? "5분봉" : "매매법"} ${fmt.int(fl.above)}/${fmt.int(fl.rows)}개`,
    " (참고 · 수익률 순일 때만 끼움)");
}

// ---------------------------------------------------------------- the judged-account progress (counts only)
/**
 * judgedProgress(board) -> [{id, ko, tfs, n, ready, byTf: [{tf, n, ready}]}] for the groups that are judged, plus
 * {obs4h, flips, extras}. "ready" = accounts with at least 30 closed trades: progress, NEVER a pass or a fail.
 */
export function judgedProgress(board) {
  const rows = (board && board.accounts) || [];
  const groups = [];
  for (const [id, kinds] of [["core", ["strategy"]], ["ds", ["ds200"]], ["m5", ["reel"]]]) {
    const tfs = judgedTfs(board, kinds[0]);
    const mine = rows.filter((a) => kinds.includes(a.kind) && tfs.includes(a.timeframe));
    if (!mine.length) continue;
    groups.push({id, ko: id === "m5" ? "5분봉 매매법" : groupKo(id), tfs, n: mine.length,
      ready: mine.filter((a) => (a.trades || 0) >= MIN_TRADES).length,
      byTf: tfs.map((tf) => {
        const t = mine.filter((a) => a.timeframe === tf);
        return {tf, n: t.length, ready: t.filter((a) => (a.trades || 0) >= MIN_TRADES).length};
      })});
  }
  const judgedKinds = Object.keys(JUDGED);
  return {
    groups,
    n: groups.reduce((s, g) => s + g.n, 0),
    ready: groups.reduce((s, g) => s + g.ready, 0),
    obs4h: rows.filter((a) => judgedKinds.includes(a.kind) && a.timeframe === "4h").length,
    flips: rows.filter((a) => a.kind === "random").length,
    extras: rows.filter((a) => fmt.groupOf(a) === "extra").length,
  };
}

/** A thin neutral progress bar (accent, never green/red: progress is not a verdict). */
export function progBar(ratio, label) {
  const r = Math.max(0, Math.min(1, ratio || 0));
  return h("div", {class: "prog", role: "progressbar", "aria-label": label, "aria-valuemin": "0", "aria-valuemax": "100",
    "aria-valuenow": String(Math.round(r * 100))}, h("i", {style: {"--p": Math.round(r * 1000) / 10 + "%"}}));
}

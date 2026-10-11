// 순위표 '표' view, 봉별 요약 and the CSV (RANK builder), copied from the rule bot's v4 board-table.js / board.js
// tfTable and fitted to the 후보 리그: the dense sortable table keeps the columns the 후보 리그's table had (한 번 평균,
// 기본값보다, 동전보다, 후보 기준, 백테스트 대비, 성격, 익절·손절) next to the rule bot's (순위, 잔고 수익률, 잔고, 낙폭,
// 상태 with the live position pill). A hidden DeepSeek row says 개수만 / 숨김 in every money cell, and the CSV leaves
// those cells empty. DOM only through h(); the CSV is built in the page from data it already has.
import {h} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import * as LK from "../lk.js";
import {TFS, tfKo, ROLE_SHORT} from "../labels.js";
import {EQUITY, GROUPS, hidden, walletRet, retPct, nameBits, kindKo, candVs, rowVsFlip, cmpVsCand, groupRows, ranking} from "./rank-cards.js";

const HID = "딥시크 금액 숨김 설정: 개수와 라벨만";
const hid = (t = "숨김") => h("span", {class: "muted", title: HID}, t);
const mark = (v, title) => (v == null ? h("span", {class: "muted", title: title || "비교할 거래가 아직 없거나 해당 없음"}, "—")
  : h("span", {class: ["cl-vs", v ? "up" : "down"], title: title || null}, v ? "▲" : "▼"));

/** The 기본값보다 / 동전보다 mark of a row (a 1/4 account is compared by drawdown on its card; labels for hidden picks). */
function vsBaseOf(d, ix, a) {
  if (a.role === "cand") return candVs(d, ix, a, "base");
  if (a.role === "exitonly" || a.role === "flip") {
    if (hidden(a, d)) return null;
    const pk = LK.pickOf(a, ix);
    const b = pk ? (ix.sets[pk.id] || {}).base : null;
    return b && !hidden(b, d) ? LK.better(a, b) : null;
  }
  return null;
}

/**
 * rankTable({onRow, pill}) -> {el, set(rows, d, ix, rank, keep)}: the dense table (50 rows a page, a click on a head
 * sorts by it). pill(a) -> the live position pill (the screen keeps it ticking).
 */
export function rankTable(o = {}) {
  let D = null, IX = null, RANK = new Map(), MIXED = true;
  const isHid = (r) => hidden(r, D);
  const tbl = K4.boardTable({
    page: 50, cls: "rk-table", sort: {id: "rk", dir: 1},
    onRow: (a) => o.onRow && o.onRow(a),
    rowCls: (a) => [a.bust ? "cl-bust" : "", a.role === "flip" ? "k4-flip" : "", isHid(a) ? "rk-cotr" : ""].join(" "),
    empty: "맞는 계좌가 없습니다",
    cols: [
      {id: "rk", label: "순위", dir: 1, sort: (a) => (RANK.has(a.id) ? RANK.get(a.id) : null), get: (a) => h("span", {class: "num muted"}, RANK.has(a.id) ? fmt.int(RANK.get(a.id)) : "—")},
      {id: "name", label: "계좌", l: true, sort: (a) => `${LK.stratKo(a.name)} ${a.tf} ${a.role}`,
        get: (a) => h("a", {class: "k4-name rk-tname", href: `#/account/${encodeURIComponent(a.id)}`, title: a.id}, nameBits(a, {role: MIXED, size: 18}))},
      {id: "kind", label: "종류", l: true, sort: (a) => a.kind, get: (a) => LK.kindChip(a.kind)},
      {id: "n", label: "거래", sort: (a) => a.trades, get: (a) => h("span", {class: "num"}, fmt.int(a.trades), a.trades < 30 ? h("small", {class: "muted"}, " 적음") : null)},
      {id: "win", label: "승률", sort: (a) => LK.winRate(a), get: (a) => (a.trades ? h("span", {class: "num"}, LK.winTxt(a), h("small", {class: "k4-wl"}, ` ${fmt.int(a.wins)}승 ${fmt.int(a.trades - a.wins)}패`)) : "—")},
      {id: "wret", label: "잔고 수익률", title: "잔고 ÷ 5,000 − 1 (닫힌 거래 기준) · 순위의 기준", sort: (a) => walletRet(a, D),
        get: (a) => { if (isHid(a)) return hid("개수만"); const r = walletRet(a, D), t = retPct(r); return h("span", {class: ["num", fmt.tone(r, t)]}, t); }},
      {id: "mean", label: "한 번 평균", title: "닫힌 거래마다 그 직전 지갑 대비 손익의 평균 (점검과 같은 단위)", sort: (a) => (isHid(a) ? null : a.mean_ret),
        get: (a) => (isHid(a) ? hid() : LK.ret(a.mean_ret))},
      {id: "vb", label: "기본값보다", title: "같은 후보의 기본값 계좌보다 한 번 평균이 위·아래 (참고)", sort: (a) => { const v = vsBaseOf(D, IX, a); return v == null ? null : v ? 1 : 0; },
        get: (a) => mark(vsBaseOf(D, IX, a), a.role === "quarter" ? "1/4 크기는 낙폭으로만 비교 (비교 계좌 카드)" : null)},
      {id: "vf", label: "동전보다", title: "같은 후보의 동전 계좌보다 한 번 평균이 위·아래 (참고)", sort: (a) => { const v = rowVsFlip(D, IX, a); return v == null ? null : v ? 1 : 0; },
        get: (a) => mark(rowVsFlip(D, IX, a), a.role === "quarter" ? "1/4 크기는 낙폭으로만 비교 (비교 계좌 카드)" : isHid(a) ? "점검 라벨 (30번부터)" : null)},
      {id: "vc", label: "후보보다", title: "비교 계좌가 자기 후보보다 나은가 (청산만·기본값: 한 번 평균, 1/4: 낙폭) · 참고", sort: (a) => { const v = cmpVsCand(D, IX, a); return v == null ? null : v ? 1 : 0; },
        get: (a) => (a.role === "cand" || a.role === "flip" ? "—" : mark(cmpVsCand(D, IX, a), a.role === "quarter" ? "1/4: 후보보다 최대 낙폭이 작으면 ▲" : null))},
      {id: "v", label: "후보 기준", title: "후보 계좌의 기준 (30번 이상: 평균 > 0 · 기본값보다 · 동전보다)",
        get: (a) => (a.role === "cand" ? h("span", {class: "cl-vcell"}, LK.verdictPill(((D && D.judge) || {})[a.id]),
          (((D && D.judge) || {})[a.id] || {}).band && ((D.judge[a.id] || {}).band || {}).below ? LK.bandMark(D.judge[a.id]) : null) : "—")},
      {id: "band", label: "백테스트 대비", title: "후보의 한 번 평균이 자기 5년 시험 기간 범위의 어디쯤인지 (참고)",
        sort: (a) => (a.role === "cand" && !isHid(a) ? LK.bandPos(a).key : null), get: (a) => (a.role === "cand" && !isHid(a) ? LK.bandPos(a).el : "—")},
      {id: "wallet", label: "잔고", sort: (a) => (isHid(a) ? null : a.wallet),
        get: (a) => { if (isHid(a)) return hid(); if (a.wallet == null) return "—"; const t = fmt.num(a.wallet, 2); return h("span", {class: ["num", fmt.tone(a.wallet - EQUITY, t)]}, t); }},
      {id: "dd", label: "최대 낙폭", sort: (a) => (isHid(a) ? null : a.max_dd), get: (a) => (isHid(a) ? hid() : LK.ddTxt(a))},
      {id: "pos", label: "상태", l: true, title: "열린 포지션 (ROE = 지금 마크 가격 기준, 나갈 때 수수료 전) · 파산 · 대기",
        sort: (a) => (a.open ? 0 : a.bust ? 2 : 1), get: (a) => (a.bust ? K4.pill("파산", "bad") : a.open && o.pill ? o.pill(a) : h("span", {class: "muted"}, "대기"))},
      {id: "style", label: "성격", l: true, sort: (a) => ((LK.pickMeta((LK.pickOf(a, IX) || a).id) || {}).style || ""),
        get: (a) => LK.styleChip((LK.pickMeta((LK.pickOf(a, IX) || a).id) || {}).style) || "—"},
      {id: "exit", label: "익절 · 손절", l: true, get: (a) => h("span", {class: "cl-exit", title: a.exit_ko}, LK.exitShort(a.exit_ko))},
    ]});
  return {
    el: tbl.el,
    /** mixed: the rows mix roles (비교 계좌, 전체): each name carries its role chip. */
    set(rows, d, ix, rank, keep, mixed = true) { D = d; IX = ix; RANK = rank || new Map(); MIXED = mixed; tbl.set(rows, keep); },
  };
}

// ---------------------------------------------------------------- 봉별 요약 (참고)
/**
 * tfSummary(d, ix, g, sub) -> a table: per timeframe (per 묶음 for 전체) 계좌, 포지션, 파산, 잔고 중앙값, 최고 계좌, and
 * (not for the 동전 묶음) the same-timeframe 동전 median and how many beat their own 동전 (참고). Hidden accounts are
 * counted and left out of every money cell.
 */
export function tfSummary(d, ix, g, sub) {
  const accts = (d && d.accounts) || [];
  const shown = (rows) => rows.filter((a) => !hidden(a, d));
  const best = (rows) => ranking(d, rows).shown[0] || null;
  const bestCell = (a) => (a ? h("a", {class: "rk-best", href: `#/account/${encodeURIComponent(a.id)}`, title: a.id},
    h("span", {class: "an-n"}, `${LK.stratKo(a.name)} · ${tfKo(a.tf)}${a.role !== "cand" ? ` · ${ROLE_SHORT[a.role]}` : ""}`), " ",
    h("b", {class: ["num", fmt.tone(walletRet(a, d))]}, fmt.num(a.wallet, 2))) : "—");
  const medWallet = (rows) => {
    const s = shown(rows);
    if (!s.length) return rows.length ? hid() : "—";
    return fmt.num(K4.median(s.map((a) => Number(a.wallet))), 2);
  };
  const vs = (rows) => {
    const xs = rows.map((a) => rowVsFlip(d, ix, a)).filter((v) => v != null);
    return xs.length ? `위 ${fmt.int(xs.filter(Boolean).length)} · 아래 ${fmt.int(xs.filter((v) => !v).length)}` : "—";
  };
  const flips = (tf, kind) => accts.filter((a) => a.role === "flip" && (!tf || a.tf === tf) && (!kind || a.kind === kind));
  const common = [
    {label: "계좌", get: (r) => fmt.int(r.rows.length)},
    {label: "포지션", get: (r) => fmt.int(r.rows.filter((a) => a.open).length)},
    {label: "파산", get: (r) => fmt.int(r.rows.filter((a) => a.bust).length)},
    {label: "잔고 중앙값", get: (r) => medWallet(r.rows)},
    {label: "최고 계좌", l: true, get: (r) => bestCell(best(r.rows))},
  ];
  if (g === "all") {
    const rows = GROUPS.map((x) => ({key: x.short, g: x.id, rows: groupRows(d, x.id)})).filter((r) => r.rows.length);
    return ui.table([{label: "묶음", l: true, get: (r) => r.key}, ...common,
      {label: "동전보다 위·아래 (참고)", get: (r) => (r.g === "flip" ? "—" : vs(r.rows))}], rows, {cls: "rk-tf", caption: "묶음별 요약"});
  }
  const mine = groupRows(d, g, sub);
  const kind = g === "core" || g === "ds" ? g : null;
  const rows = TFS.filter((tf) => mine.some((a) => a.tf === tf)).map((tf) => ({key: tfKo(tf), tf, rows: mine.filter((a) => a.tf === tf)}));
  const cols = [{label: "봉", l: true, get: (r) => r.key}, ...common];
  if (g !== "flip") {
    cols.push({label: "동전 잔고 중앙값", title: "같은 봉 동전 계좌들의 잔고 중앙값", get: (r) => medWallet(flips(r.tf, kind))},
      {label: "동전보다 위·아래 (참고)", title: "자기 후보의 동전 계좌보다 한 번 평균이 위·아래인 계좌 수", get: (r) => vs(r.rows)});
  }
  return rows.length ? ui.table(cols, rows, {cls: "rk-tf", caption: "봉별 요약"}) : ui.empty("계좌가 없습니다");
}

// ---------------------------------------------------------------- CSV
export const CSV_HEAD = ["rank", "account", "role", "kind", "strategy", "tf", "exit", "trades", "wins", "wallet_return", "mean_per_trade",
  "wallet", "max_dd", "open", "vs_flip", "bust", "money_hidden"];
/** The CSV rows of the shown accounts (fractions as numbers for a spreadsheet); a hidden account's money cells empty. */
export function csvRows(d, ix, rows, rank) {
  return rows.map((a) => {
    const co = hidden(a, d);
    const v = rowVsFlip(d, ix, a);
    const p = a.open;
    const open = p ? `${fmt.coin(String(p.symbol || "").replace(/T$/, ""))} ${Number(p.side) > 0 ? "롱" : "숏"}${!co && p.lev ? ` ${p.lev}배` : ""}` : "";
    return [rank && rank.has(a.id) ? rank.get(a.id) : "", a.id, a.role, a.kind, a.name, a.tf, a.exit, a.trades, a.wins,
      co ? "" : walletRet(a, d) ?? "", co ? "" : a.mean_ret ?? "", co ? "" : a.wallet ?? "", co ? "" : a.max_dd ?? "", open,
      v == null ? "" : v ? "위" : "아래", a.bust ? "yes" : "", co ? "yes" : ""];
  });
}
export const kindLabel = kindKo;

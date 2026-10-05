// 딥시크 17계열 요약 (gap batch B; promised to the owners 10/05 20:09 "딥시크 44개 가족별 요약"): one row per DeepSeek
// family, counted from the shared /api/board rows (no new route, no extra polling: it repaints when the board does):
// definitions, accounts, closed trades, win rate, busts. Below them the DeepSeek total and, as the baseline, the coin
// flips of the same timeframes (15분·30분·1시간·4시간; the 5m flips belong to the reel).
// HONESTY (CONTRACT section 1): DeepSeek and the coin flips are COUNTED only here, never listed with money (no P&L, no
// balance, no return); no pass / fail words or colours (the win rate stays plain ink: it is not the verdict, and a high
// win rate can still lose money, which the note says); 표본 적음 under 30 trades; refNote. A family row opens that
// family's definitions (strategies-list.js); the grid's DeepSeek tab links here (#/strategies?g=ds&fam=all).
import {h, put, ui, fmt, motion, dsFamilyOf} from "../core/pb.js";
import {DS_FAMILIES} from "./strategies-defs.js";

/** The DeepSeek timeframes (config: 39 definitions x 4, the 5 session ones x 3): the coin flips counted beside them. */
export const DS_TFS = ["15m", "30m", "1h", "4h"];
const MIN_TRADES = 30;           // the verdict's own floor (checkpoint.MIN_TRADES): fewer = 표본 적음

const blank = (id, ko) => ({id, ko, defs: 0, accounts: 0, trades: 0, wins: 0, losses: 0, bust: 0, open: 0, rate: null});
function add(r, a) {
  r.accounts++;
  r.trades += Number(a.trades) || 0;
  r.wins += Number(a.wins) || 0;
  r.losses += Number(a.losses) || 0;
  if (a.bust) r.bust++;
  if (a.position) r.open++;
}
const famOf = (a) => a.family || (a.data && a.data.family) || dsFamilyOf(a.strategy);

/**
 * familyStats(board) -> {rows: [{id, ko, defs, accounts, trades, wins, losses, rate, bust, open}] (F1..F17 in order),
 * total: the same over every DeepSeek account, coin: the coin flips of the DeepSeek timeframes (null when none)}.
 * Counts only: the rows carry no money field at all.
 */
export function familyStats(board) {
  const acc = (board && Array.isArray(board.accounts)) ? board.accounts : [];
  const by = new Map(DS_FAMILIES.map((f) => [f.id, blank(f.id, f.ko)]));
  const defs = new Map(DS_FAMILIES.map((f) => [f.id, new Set()]));
  const total = blank("all", "딥시크 전체"), coin = blank("coin", "동전 봇 · 같은 봉 기준선");
  const allDefs = new Set();
  for (const a of acc) {
    const g = fmt.groupOf(a);
    if (g === "ds") {
      add(total, a);
      allDefs.add(a.strategy);
      const f = famOf(a);
      if (!by.has(f)) continue;
      add(by.get(f), a);
      defs.get(f).add(a.strategy);
    } else if (g === "coin" && DS_TFS.includes(a.timeframe)) add(coin, a);
  }
  for (const [f, r] of by) r.defs = defs.get(f).size;
  total.defs = allDefs.size;
  const fin = (r) => { r.rate = r.trades ? r.wins / r.trades : null; return r; };
  return {rows: [...by.values()].map(fin), total: fin(total), coin: coin.accounts ? fin(coin) : null};
}

const COLS = [["defs", "정의"], ["accounts", "계좌"], ["trades", "거래"], ["rate", "승률"], ["bust", "파산"]];
const cellText = (r, k) => (k === "rate" ? fmt.pct(r.rate, 0, false) : k === "defs" && r.id === "coin" ? "—" : fmt.int(r[k]));
const ariaOf = (r) => `${r.id === "all" || r.id === "coin" ? "" : r.id + " "}${r.ko}: 정의 ${r.id === "coin" ? "없음" : fmt.int(r.defs) + "개"}, 계좌 ${fmt.int(r.accounts)}개, `
  + `거래 ${fmt.int(r.trades)}건, 승률 ${fmt.pct(r.rate, 0, false)}, 파산 ${fmt.int(r.bust)}개`;

/** One line of counts for a family's own card (strategies-list.js family view): "계좌 12 · 거래 140건 · 승률 52% · 파산 0". */
export function familyLine(r) {
  if (!r) return null;
  return h("p", {class: "dsf-line"}, h("span", {class: "pp ref"}), " ",
    `계좌 ${fmt.int(r.accounts)}개 · 거래 ${fmt.int(r.trades)}건 · 승률 ${fmt.pct(r.rate, 0, false)} · 파산 ${fmt.int(r.bust)}개`, " ",
    ui.smallSample(r.trades, MIN_TRADES));
}

/**
 * dsFamilyCard(ctx, {onPick, verdictTs}) -> {el, update(board)}. The card is built once; update() repaints the numbers
 * in place, and a number that really changed since the last board gets one gentle tint (motion.flash: skipped under
 * reduced motion and on a hidden page).
 */
export function dsFamilyCard(ctx, o = {}) {
  const cells = new Map();         // row id -> {row, name, small, cells: {key: el}}
  const prev = new Map();          // row id -> last painted numbers
  const mkRow = (r, kind) => {
    const name = h("span", {class: "dsf-name"},
      kind === "fam" ? h("b", {class: "dsf-id"}, r.id) : null,
      h("span", {class: "dsf-ko"}, r.ko),
      kind === "coin" ? h("span", {class: "pp ref"}) : null);
    const small = h("span", {class: "dsf-small"});
    name.append(small);
    const cs = {};
    const kids = [name, ...COLS.map(([k, l]) => (cs[k] = h("span", {class: ["dsf-c", "num", k === "rate" ? "dsf-rate" : ""], title: l}, "—")))];
    const row = kind === "fam"
      ? h("button", {type: "button", class: "dsf-row dsf-fam", dataset: {f: r.id}, title: `${r.id} ${r.ko} · 눌러서 정의 보기`, onclick: () => o.onPick && o.onPick(r.id)}, kids)
      : h("div", {class: ["dsf-row", kind === "all" ? "dsf-total" : "dsf-coin"], role: "group"}, kids);
    cells.set(r.id, {row, small, cells: cs});
    return row;
  };
  const head = h("div", {class: "dsf-row dsf-head", "aria-hidden": "true"}, h("span", {class: "dsf-name"}, "계열"),
    COLS.map(([, l]) => h("span", {class: "dsf-c"}, l)));
  const famBox = h("div", {class: "dsf-list", role: "list", "aria-label": "딥시크 17계열"});
  const footBox = h("div", {class: "dsf-foot"});
  const ref = h("div");
  const el = ui.card({plate: "딥시크 17계열 요약", sub: "계열마다 셈만 · 돈 숫자 없음", cls: "dsf-card"},
    h("p", {class: "ink2 dsf-intro"}, "딥시크 정의 44개를 17계열로 묶어 셌습니다. 계열을 누르면 그 계열의 정의가 열립니다."),
    h("div", {class: "dsf-table"}, head, famBox, footBox),
    h("ul", {class: "dsf-keys muted small"},
      h("li", null, "거래 = 닫힌 거래 수 · 승률 = 이긴 거래 ÷ 닫힌 거래 · 파산 = 잔고가 바닥나 멈춘 계좌 수"),
      h("li", null, "승률이 높아도 한 번 질 때 크게 지면 돈은 잃을 수 있습니다. 승률은 판정 기준이 아닙니다."),
      h("li", null, `맨 아래 동전 봇 = 같은 봉(15분·30분·1시간·4시간) 동전 던지기 계좌: 견줄 때 쓰는 기준선입니다.`)),
    ref,
    h("div", {class: "row wrap dsf-acts"},
      h("a", {class: "btn-line", href: ctx.href("grid", null, {g: "ds"})}, "한눈 지도에서 보기"),
      h("a", {class: "btn-line", href: ctx.href("board", null, {g: "ds"})}, "순위표에서 보기")));
  let built = false;

  function paintRow(r) {
    const c = cells.get(r.id);
    if (!c) return;
    const was = prev.get(r.id);
    for (const [k] of COLS) {
      const t = cellText(r, k);
      const e = c.cells[k];
      if (e.textContent === t) continue;
      e.textContent = t;
      // a real change since the last board (never on the first paint): one tint, a new bust in the loss colour
      if (was && ["trades", "bust"].includes(k) && was[k] !== r[k]) motion.flash(e, k === "bust" ? "down" : null);
    }
    c.cells.bust.classList.toggle("down", r.bust > 0);
    put(c.small, r.id === "coin" ? null : ui.smallSample(r.trades, MIN_TRADES));
    c.row.setAttribute("aria-label", ariaOf(r));
    prev.set(r.id, {trades: r.trades, bust: r.bust});
  }

  return {
    el,
    update(board) {
      const fs = familyStats(board);
      if (!built) {
        put(famBox, fs.rows.map((r) => h("div", {role: "listitem", class: "dsf-li"}, mkRow(r, "fam"))));
        put(footBox, mkRow(fs.total, "all"), fs.coin ? mkRow(fs.coin, "coin") : null);
        built = true;
      } else if (fs.coin && !cells.has("coin")) footBox.append(mkRow(fs.coin, "coin"));
      for (const r of fs.rows) paintRow(r);
      paintRow(fs.total);
      if (fs.coin) paintRow(fs.coin);
      put(ref, ui.refNote(o.verdictTs ? o.verdictTs() : null, "딥시크는 계좌마다 동전 봇과 비교하지 않고 계열·묶음으로만 셉니다."));
      return fs;
    },
  };
}

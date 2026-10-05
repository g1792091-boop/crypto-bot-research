// 분석 (builder C): the one card style every analysis view uses, so the eleven views read alike.
//   viewHead: plate + the question in plain words + what it stands on (sample, computed time) + how to read it.
//   thin: the small-sample warning line.  cell: "n건 · 승률 · 손익" with 표본 적음.  cmpList: rows of label → 매매법 / 동전 봇.
//   dimSeg: a remembered segmented switch inside a view.  acctLabel: a Korean account name (DeepSeek from strategies-defs).
// Every server string goes in as text (h()); numbers only through fmt.
import {h, ui, fmt, local} from "../core/pb.js";

/** {plate, q, meta, read, warn: [Node|string], at: computed_at, stale} -> the head card of a view. */
export function viewHead(o) {
  const meta = [o.meta, o.at ? `${fmt.kst(o.at)} 계산${o.stale ? " (예전 값, 다시 계산 중)" : ""}` : null].filter(Boolean).join(" · ");
  return ui.card({plate: o.plate, cls: "an-head"},
    h("h2", {class: "an-q"}, o.q),
    meta ? h("p", {class: "an-meta"}, meta) : null,
    o.read ? h("p", {class: "an-read"}, h("b", null, "읽는 법 "), o.read) : null,
    ...(o.warn || []).filter(Boolean).map((w) => (w instanceof Node ? w : h("p", {class: "an-warn"}, w))));
}

/** The warning when a view stands on too few trades (or days): no conclusion. */
export function thin(n, need, what) {
  if (n != null && n >= need) return null;
  return h("p", {class: "an-warn"}, ui.pill("표본 적음", "thin"), ` ${what} ${fmt.int(n || 0)}건 (${fmt.int(need)}건 미만). 숫자가 우연일 수 있어 여기서 결론을 내리지 않습니다.`);
}

/** The words a grouped view uses for its group (?group=, analysis.js GROUPS): who it is, its short name, its coin flips
 *  (the baseline line only: the 36 and DeepSeek against the 15m-4h flips, the reel against the three 5m flips),
 *  and whether money may be shown (DeepSeek: counts and rates only, CONTRACT section 1). */
const GW = {
  core: {who: "기존 36 매매법", short: "기존 36", flips: "동전 봇", money: true,
    flipNote: "동전 봇 = 같은 청산 규칙으로 무작위로 들어가는 비교 계좌."},
  ds200: {who: "딥시크 44개 정의", short: "딥시크", flips: "동전 봇", money: false,
    flipNote: "동전 봇 = 딥시크와 같은 청산 규칙(2 ATR 손절 + 계단 잠금)으로 같은 봉에서 무작위로 들어가는 비교 계좌."},
  reel: {who: "릴스 5분 단타", short: "릴스", flips: "5분봉 동전 봇", money: true,
    flipNote: "5분봉 동전 봇 = 릴스와 같은 청산 규칙으로 5분봉에서 롱만 무작위로 들어가는 비교 계좌 3개."},
};
export const groupWords = (g) => GW[g] || GW.core;

/** A cell "n건 · 승률 45% · −1,234.00" (+ 표본 적음 under min). c = {trades|n, win_rate|wr, pnl}.
 *  noMoney (DeepSeek): the money part is left out even if a number came. */
export function cell(c, min = 10, noMoney = false) {
  const n = c ? (c.trades ?? c.n) : 0;
  if (!c || !n) return h("span", {class: "muted"}, "—");
  const wr = c.win_rate ?? c.wr;
  const small = c.status ? c.status !== "ok" : n < min;
  return h("span", {class: "an-cell"}, h("span", {class: "num"}, `${fmt.int(n)}건`), " · ", h("span", {class: "num"}, `승률 ${fmt.pct(wr, 0, false)}`),
    c.pnl != null && !noMoney ? [" · ", h("b", {class: ["num", fmt.tone(c.pnl)]}, fmt.money(c.pnl, true))] : null,
    small ? [" ", ui.pill("표본 적음", "thin")] : null);
}

/** Rows "label → 매매법 cell / 동전 봇 cell" (phones: stacked; PC: three columns). */
export function cmpList(rows, o = {}) {
  return h("div", {class: "an-cmp", role: "list"},
    h("div", {class: "an-cmprow an-cmphead", "aria-hidden": "true"}, h("span", null, o.label || ""), h("span", null, o.a || "매매법"), h("span", null, o.b || "동전 봇 (참고)")),
    rows.map((r) => h("div", {class: "an-cmprow", role: "listitem"}, h("b", {class: "an-cmpk"}, r.label),
      h("span", null, h("i", {class: "an-tag"}, o.a || "매매법"), r.a), h("span", null, h("i", {class: "an-tag"}, o.b || "동전 봇"), r.b))));
}

/** A segmented switch whose choice is remembered per view (local "an-<key>"). */
export function dimSeg(key, options, def, onChange, scroll) {
  let cur = local.get("an-" + key, def);
  if (!options.some((o) => o.id === cur)) cur = def;
  const el = ui.seg(options, cur, (id) => { cur = id; local.set("an-" + key, id); onChange(id); }, {label: "보기", scroll});
  return {el, get: () => cur};
}

/** A Korean name for an account id (fmt.idName knows the 36, DeepSeek and the reel). */
export const acctLabel = (id) => fmt.idName(id);

/** A list row that opens an account. */
export const acctLink = (ctx, id, kids) => h("a", {class: "lrow click an-row", role: "listitem", href: ctx.href("account", id), title: id}, kids);

/** "+1.2%p" from a value already in percentage points. */
export const pp = (x, dec = 1) => (x == null ? "—" : `${fmt.num(x, dec, true)}%p`);

// ---------------------------------------------------------------- fill-strat: how far a view is from its real threshold
const GROUP_KIND = {core: "strategy", ds200: "ds200", reel: "reel"};

/** Per-account progress to a trade threshold, from the board: {need, total, max, done, share}. group: core | ds200 |
 *  reel (each group's own accounts, never the coin flips or copies). share = the best account's way there (0..1). */
export function tradeProgress(board, group, need) {
  const kind = GROUP_KIND[group] || "strategy";
  const rows = ((board && board.accounts) || []).filter((a) => a.kind === kind);
  const ns = rows.map((a) => Number(a.trades) || 0);
  const max = ns.length ? Math.max(...ns) : 0;
  const done = ns.filter((n) => n >= need).length;
  const sum = ns.reduce((x, y) => x + y, 0);
  return {need, total: rows.length, max, done, avg: rows.length ? sum / rows.length : 0, share: need ? Math.min(1, max / need) : 1};
}

/** Days since the group's accounts started (the earliest created_ts on the board), or null. */
export function runDays(board, group, now = Date.now()) {
  const kind = GROUP_KIND[group] || "strategy";
  const ts = ((board && board.accounts) || []).filter((a) => a.kind === kind && a.created_ts != null).map((a) => Number(a.created_ts));
  return ts.length ? Math.max(0, (now - Math.min(...ts)) / 86400000) : null;
}

/** One neon progress bar: label, the words under it, share 0..1 (filled when reached). */
export function progressBar(label, words, share) {
  const w = Math.max(0, Math.min(1, share || 0));
  return h("div", {class: ["an-prog", w >= 1 ? "full" : ""]},
    h("div", {class: "an-prog-top"}, h("b", null, label), h("span", {class: "num"}, `${fmt.num(w * 100, 0)}%`)),
    h("span", {class: "an-prog-t", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(w * 100)), "aria-label": label},
      h("i", {style: {"--w": (w * 100).toFixed(1) + "%"}})),
    h("p", {class: "an-prog-w"}, words));
}

/** The card above a view that waits for trades: its real thresholds and how far the accounts are, plus where the
 *  5-year reference can be seen now (bars: [{label, words, share}], y5: a Node or null). */
export function waitCard(title, bars, y5) {
  return ui.card({plate: "채워지는 중", sub: title, cls: "an-wait"}, ...bars.map((b) => progressBar(b.label, b.words, b.share)), y5 || null,
    h("p", {class: "an-note"}, "막대는 지금 계좌들의 실제 거래 수입니다. 기준을 넘으면 이 보기가 숫자로 채워집니다."));
}

/** A thin horizontal share bar (0..1) in a meaning colour ("up" | "down" | "acc"). */
export const shareBar = (share, tone = "acc") => h("span", {class: ["an-bar", tone]}, h("i", {style: {"--w": Math.max(0, Math.min(1, share || 0)) * 100 + "%"}}));
